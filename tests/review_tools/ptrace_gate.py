"""Review-only x86_64 Linux syscall-boundary observer, no product import/patch."""
import os,signal,time,ctypes,errno,pathlib,json
libc=ctypes.CDLL(None,use_errno=True)
libc.ptrace.argtypes=[ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_void_p];libc.ptrace.restype=ctypes.c_long
class Regs(ctypes.Structure):
 _fields_=[(n,ctypes.c_ulonglong) for n in 'r15 r14 r13 r12 rbp rbx r11 r10 r9 r8 rax rcx rdx rsi rdi orig_rax rip cs eflags rsp ss fs_base gs_base ds es fs gs'.split()]
def ptrace(req,pid,addr=0,data=0):
 r=libc.ptrace(req,pid,ctypes.c_void_p(addr),ctypes.cast(data,ctypes.c_void_p) if not isinstance(data,int) else ctypes.c_void_p(data))
 if r==-1:raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
 return r
def proc_identity(pid):
 root=pathlib.Path('/proc')/str(pid);raw=(root/'stat').read_text();start=raw.rsplit(')',1)[1].split()[19];st=(root/'exe').stat()
 return {'pid':pid,'starttime':start,'exe':str((root/'exe').resolve()),'exeDev':st.st_dev,'exeIno':st.st_ino,'argv':(root/'cmdline').read_bytes().replace(b'\0',b' ').decode(),'cwd':str((root/'cwd').resolve())}
def trace(command,cwd,output,callback,*,timeout=180,env=None):
 output=pathlib.Path(output);fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 pid=os.fork()
 if pid==0:
  try:
   os.dup2(fd,1);os.dup2(fd,2);os.close(fd);os.chdir(cwd)
   ptrace(0,0);os.kill(os.getpid(),signal.SIGSTOP)
   os.execvpe(command[0],command,dict(os.environ,**(env or {})))
  except BaseException:os._exit(125)
 os.close(fd);result={'pid':pid,'command':command,'cwd':cwd,'started':time.time(),'timeout':timeout,'waitBoundaryCount':0,'killSent':False};paused=False;alive=True;birth=None;tracing=True
 deadline=time.monotonic()+timeout
 try:
  _,st=os.waitpid(pid,0);paused=True;birth=proc_identity(pid)['starttime']
  ptrace(0x4200,pid,0,1|16) # TRACESYSGOOD | TRACEEXEC, NOT EXITKILL
  forward=0
  while True:
   if paused:ptrace(24,pid,0,forward);paused=False;forward=0
   while True:
    got,st=os.waitpid(pid,os.WNOHANG)
    if got:break
    if time.monotonic()>deadline:raise TimeoutError('BOUNDED_REVIEW_TRACE_TIMEOUT')
    time.sleep(.0005)
   if os.WIFEXITED(st) or os.WIFSIGNALED(st):
    alive=False;result.update(waitStatus=st,exitCode=os.waitstatus_to_exitcode(st),ended=time.time());return result
   paused=True;sig=os.WSTOPSIG(st)
   if sig==signal.SIGTRAP|0x80:
    r=Regs();ptrace(12,pid,0,ctypes.byref(r))
    if r.orig_rax==61 and 0<r.rax<(1<<63):
     result['waitBoundaryCount']+=1
     ident=proc_identity(pid)
     if ident['starttime']!=birth:raise RuntimeError('PID_START_CHANGED')
     action=callback(pid,ident,result)
     if action == 'observe-completion':
      ptrace(17,pid,0,0);paused=False;tracing=False
      result['observerDetachedAt']=time.time()
      while True:
       got,st=os.waitpid(pid,os.WNOHANG)
       if got:
        alive=False;result.update(waitStatus=st,exitCode=os.waitstatus_to_exitcode(st),ended=time.time());return result
       if time.monotonic()>deadline:raise TimeoutError('BOUNDED_REVIEW_COMPLETION_TIMEOUT')
       time.sleep(.02)
     if action:
      result['killSent']=True;os.kill(pid,signal.SIGKILL)
      _,st=os.waitpid(pid,0);alive=False
      result.update(waitStatus=st,exitCode=os.waitstatus_to_exitcode(st),ended=time.time());return result
   elif sig not in (signal.SIGTRAP,signal.SIGSTOP):forward=sig
 finally:
  if alive and tracing:
   # A trace timeout/exception must resume only this exact live child.
   try:
    ident=proc_identity(pid)
    if birth is not None and ident['starttime']==birth:
     if not paused:
      os.kill(pid,signal.SIGSTOP);os.waitpid(pid,0);paused=True
     ptrace(17,pid,0,0);os.kill(pid,signal.SIGCONT);result['cleanup']='detached-and-resumed-exact-child'
   except FileNotFoundError:result['cleanup']='child-already-exited-no-signal'
