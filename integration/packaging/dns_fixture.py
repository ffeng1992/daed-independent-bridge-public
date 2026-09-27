"""Synthetic DNS only; valid UDP/TCP replies without upstream access."""
import signal
from dnslib import A,RR,QTYPE
from dnslib.server import DNSServer,BaseResolver
class Resolver(BaseResolver):
    def resolve(self,request,handler):
        reply=request.reply()
        if request.q.qtype==QTYPE.A:reply.add_answer(RR(request.q.qname,QTYPE.A,rdata=A('192.0.2.99'),ttl=30))
        return reply
resolver=Resolver()
for tcp in (False,True):DNSServer(resolver,address='127.0.0.1',port=15353,tcp=tcp).start_thread()
signal.pause()
