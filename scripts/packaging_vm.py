"""Disposable CI-only QEMU VM. Bootstrap network is removed before any acceptance."""
import sys, argparse, hashlib, json, os, pathlib, shutil, socket, subprocess, tarfile, time, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'out/packaging-vm'
EVIDENCE=ROOT/'out/packaging-evidence'
def check(ok,code):
    if not ok:raise RuntimeError(code)
def run(*args):subprocess.run(args,check=True,cwd=ROOT)

def run_vm(*, local_packaging=False, browser=False, ui_matrix=False):
    bootstrap='integration/packaging/bootstrap.sh'
    check(not OUT.exists() and not EVIDENCE.exists(),'FRESH_PACKAGING_VM_REQUIRED')
    OUT.mkdir(parents=True,exist_ok=True)
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    if ui_matrix:(EVIDENCE/'ui-matrix-enabled').touch()
    check(os.environ.get('GITHUB_ACTIONS')=='true' or (local_packaging and bootstrap=='integration/packaging/bootstrap.sh'),'DISPOSABLE_CI_ONLY')
    lock=json.loads((ROOT/'integration/packaging/vm.lock.json').read_text())
    image=OUT/'base.qcow2'
    if not (local_packaging and image.exists()):
        with urllib.request.urlopen(lock['image'],timeout=120) as response,image.open('wb') as output:shutil.copyfileobj(response,output)
    check(hashlib.sha512(image.read_bytes()).hexdigest()==lock['sha512'],'VM_IMAGE_HASH')
    run('qemu-img','create','-f','qcow2','-F','qcow2','-b',str(image),str(OUT/'disk.qcow2'),'12G')
    source=OUT/'payload';source.mkdir()
    check((ROOT/'.git').exists(),'COMMITTED_PUBLIC_CHECKOUT_REQUIRED')
    run('git','diff','--exit-code');run('git','diff','--cached','--exit-code')
    archive=OUT/'source.tar';archive.write_bytes(subprocess.check_output(['git','archive','HEAD'],cwd=ROOT))
    with tarfile.open(archive) as tar:tar.extractall(source,filter='data')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip()
    (source/'official').mkdir()
    for name,pin in json.loads((ROOT/'upstream.lock.json').read_text())['components'].items():
        raw=urllib.request.urlopen(pin['url'],timeout=120).read()
        check(hashlib.sha256(raw).hexdigest()==pin['sha256'],'OFFICIAL_ARCHIVE_HASH')
        (source/'official'/f'{name}.zip').write_bytes(raw)
        if bootstrap=='integration/packaging/bootstrap.sh':
            from scripts.release_prepare import verify_archive
            files=verify_archive(raw,pin)
            executable=next(p for p in files if p.endswith(name+'-linux-x86_64'))
            binary=source/'official'/name;binary.write_bytes(files[executable]);binary.chmod(0o555)
    (EVIDENCE/'candidate-commit.txt').write_text(commit+'\n')
    user_data='''#cloud-config
    users: []
    disable_root: true
    ssh_pwauth: false
    package_update: true
    packages: [python3-pip, python3-dnslib, bind9-dnsutils, dnsdist, openssl, iproute2, ca-certificates]
    runcmd:
      - [mkdir, -p, /mnt/project, /evidence]
      - [mount, -t, 9p, -o, "trans=virtio,version=9p2000.L,ro", project, /mnt/project]
      - [mount, -t, 9p, -o, "trans=virtio,version=9p2000.L", evidence, /evidence]
      - [cp, -a, /mnt/project, /opt/bridge]
      - [bash, /opt/bridge/integration/packaging/bootstrap.sh]
    '''
    (OUT/'user-data').write_text(user_data);(OUT/'meta-data').write_text('instance-id: bridge-packaging-disposable\nlocal-hostname: bridge-packaging\n')
    if browser:
        (OUT/'network-config').write_text('version: 2\nethernets:\n  bootstrap:\n    match: {macaddress: "52:54:00:12:34:55"}\n    dhcp4: true\n  management:\n    match: {macaddress: "52:54:00:12:34:56"}\n    dhcp4: false\n    dhcp6: false\n    optional: true\n')
    if local_packaging and sys.platform=='darwin':
        seed=OUT/'cidata';seed.mkdir()
        shutil.copy(OUT/'user-data',seed/'user-data');shutil.copy(OUT/'meta-data',seed/'meta-data')
        if browser:shutil.copy(OUT/'network-config',seed/'network-config')
        run('hdiutil','makehybrid','-iso','-joliet','-default-volume-name','cidata','-o',str(OUT/'seed.iso'),str(seed))
        (OUT/'seed.iso').rename(OUT/'seed.img')
    else:
        run('cloud-localds',*(['--network-config',str(OUT/'network-config')] if browser else []),str(OUT/'seed.img'),str(OUT/'user-data'),str(OUT/'meta-data'))
    qmp=OUT/'qmp.sock'
    management=[]
    if browser:
        check(local_packaging,'BROWSER_LOCAL_ONLY')
        (EVIDENCE/'browser-enabled').touch()
        management=['-netdev','user,id=management,net=198.18.0.0/24,restrict=on,hostfwd=tcp:127.0.0.1:12023-198.18.0.15:2023','-device','virtio-net-pci,netdev=management,mac=52:54:00:12:34:56']
    accelerator='kvm' if os.access('/dev/kvm',os.R_OK|os.W_OK) else 'tcg'
    (EVIDENCE/'vm.json').write_text(json.dumps(dict(lock,accelerator=accelerator,bootstrapNetwork='removed-before-probe',testNetwork='guest-only'),indent=2))
    with (EVIDENCE/'serial.log').open('wb') as serial:
        proc=subprocess.Popen(['qemu-system-x86_64','-accel',accelerator,'-cpu','host' if accelerator=='kvm' else 'max','-m','4096','-smp','2','-nographic',
            '-drive',f'file={OUT}/disk.qcow2,if=virtio,format=qcow2','-drive',f'file={OUT}/seed.img,if=virtio,format=raw',
            '-netdev','user,id=bootstrap','-device','virtio-net-pci,netdev=bootstrap,id=bootstrap-nic,mac=52:54:00:12:34:55',
            '-virtfs',f'local,path={source},mount_tag=project,security_model=none,readonly=on',
            '-virtfs',f'local,path={EVIDENCE},mount_tag=evidence,security_model=none',
            '-qmp',f'unix:{qmp},server=on,wait=off',*management],stdout=serial,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+(2400 if local_packaging else 900)
            while not (EVIDENCE/'bootstrap-ready').exists():
                check(proc.poll() is None and time.monotonic()<deadline,'VM_BOOTSTRAP_FAILED')
                check(b'Failed to run module scripts-user' not in (EVIDENCE/'serial.log').read_bytes(),'VM_CLOUD_INIT_FAILED')
                time.sleep(2)
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.connect(str(qmp));f=client.makefile('rwb');f.readline()
                for command in ({'execute':'qmp_capabilities'},{'execute':'device_del','arguments':{'id':'bootstrap-nic'}},{'execute':'netdev_del','arguments':{'id':'bootstrap'}}):
                    f.write((json.dumps(command)+'\n').encode());f.flush()
                    while True:
                        value=json.loads(f.readline())
                        check('error' not in value,'VM_NETWORK_REMOVAL')
                        if 'return' in value:break
            (EVIDENCE/'network-detached').touch()
            deadline=time.monotonic()+(2400 if local_packaging else 900)
            while proc.poll() is None:
                check(time.monotonic()<deadline,'VM_ACCEPTANCE_TIMEOUT')
                serial_bytes=(EVIDENCE/'serial.log').read_bytes()
                check(not any(marker in serial_bytes for marker in (b'You are in emergency mode',b'EVIDENCE_CHANNEL_NOT_READY',b'EVIDENCE_VOLUME_IDENTITY')),'VM_BOOT_EVIDENCE_FAILED')
                time.sleep(2)
            record=json.loads((EVIDENCE/'packaging-result.json').read_text())
            print(json.dumps(record))
            check(record['checkoutSha']==commit and record['passed'] is True,'PACKAGING_VM_FAILED')
        finally:
            if proc.poll() is None:proc.kill();proc.wait()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local',action='store_true')
    parser.add_argument('--browser',action='store_true')
    parser.add_argument('--ui-matrix',action='store_true')
    args=parser.parse_args()
    run_vm(local_packaging=args.local,browser=args.browser,ui_matrix=args.ui_matrix)
if __name__=='__main__':main()
