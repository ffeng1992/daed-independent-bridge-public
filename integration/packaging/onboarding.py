"""Synthetic user API actions for VM acceptance, never shipped as installer code.

This exercises the real upstream API behind the original HTTP frontend. It is
not a claim that a browser clicked its registration/default-resource screens.
"""
import json
from pathlib import Path
from scripts.release_setup import api,need,CFG

USERNAME='synthetic-admin'
PASSWORD='Synthetic-314159'


def prepare_user():
    need(api('{numberUsers}')['numberUsers']==0,'INSTALLER_CREATED_DAED_ACCOUNT')
    need(not (CFG/'initial-admin.json').exists(),'INITIAL_DAED_PASSWORD_FILE')
    token=api('mutation($u:String!,$p:String!){createUser(username:$u,password:$p)}',{'u':USERNAME,'p':PASSWORD})['createUser']
    need(api('{numberUsers}')['numberUsers']==1,'OFFICIAL_SIGNUP_FAILED')
    login=api('query($u:String!,$p:String!){token(username:$u,password:$p)}',{'u':USERNAME,'p':PASSWORD})['token']
    need(api('{user{username}}',token=login)['user']['username']==USERNAME,'OFFICIAL_LOGIN_FAILED')
    # User-selected synthetic LAN/DNS values, not installer defaults. Configure
    # through official mutations only, as a user does before bridge activation.
    value=json.loads((CFG/'release.json').read_text())
    config=api('mutation($g:globalInput!){createConfig(name:"Synthetic LAN",global:$g){id}}',{'g':{
        'lanInterface':[value['lanInterface']],'wanInterface':[],
        'bootstrapResolver':value['upstream'],'fallbackResolver':value['upstream'],
        'autoConfigKernelParameter':True,'disableWaitingNetwork':True}},token)['createConfig']['id']
    dns=api('mutation($s:String!){createDns(name:"Synthetic DNS",dns:$s){id}}',{'s':"bind: 'tcp+udp://127.0.0.1:5353'\nupstream { policy: 'tcp+udp://127.0.0.1:5534' }\nrouting { request { fallback: policy } response { fallback: accept } }"},token)['createDns']['id']
    routing=api('mutation($s:String!){createRouting(name:"Synthetic direct",routing:$s){id}}',{'s':'fallback: direct'},token)['createRouting']['id']
    for kind,ident in (('Config',config),('Dns',dns),('Routing',routing)):
        api('mutation($id:ID!){select'+kind+'(id:$id)}',{'id':ident},token)
    from scripts.release_lifecycle import authorize_daed
    authorize_daed(token)


def existing_account():
    need(api('{numberUsers}')['numberUsers']==1,'EXISTING_USER_COUNT_CHANGED')
    token=api('query($u:String!,$p:String!){token(username:$u,password:$p)}',{'u':USERNAME,'p':PASSWORD})['token']
    need(api('{user{username}}',token=token)['user']['username']==USERNAME,'EXISTING_ACCOUNT_CHANGED')
