# Official Daed Web field matrix — bridge release fixes

Pinned upstream: official daed v2.1.1, official Web v1.28.0, official DAE v2.1.1. No upstream files were modified.

The existing completed matrix is retained. Only the two bridge-owned rows below were retested. CONFIG_PASS proves configuration handling and validation/application, not otherwise unobserved runtime behavior.

```json
{
  "CONFIG_PASS": 160,
  "DATA_PLANE_SETTING_COUNT": 186,
  "FAIL": 18,
  "KNOWN_LIMITATION": 2,
  "RUNTIME_PASS": 61,
  "UI_CONTROL_COUNT": 241,
  "UNTESTED": 0
}
```

## Targeted bridge repairs

- `action.createGroup`: **CONFIG_PASS**. Unreferenced empty group preserved in source/IR/extensions and omitted from candidate; selected Routing reference rejected without replacing active bundle; populated/empty/deleted transitions validated and applied.
- `action.testNodeLatencies`: **RUNTIME_PASS**. CAP_NET_RAW only; actual official latency mutation/readback and unchanged official Web display distinguish two synthetic endpoints; route/interface/BPF privileged operations denied.

The original failed observations remain in the local evidence ledger. Browser fixture initialization created default resources during the first display check; the fixture was restored through official API, and only the incomplete browser witness was repeated. No complete matrix was rerun.

## Complete classification

| Control | Result | Failure owner |
|---|---|---|
| config.name | RUNTIME_PASS | — |
| config.logLevel | RUNTIME_PASS | — |
| config.tproxyPort | RUNTIME_PASS | — |
| config.allowInsecure | RUNTIME_PASS | — |
| config.checkInterval | RUNTIME_PASS | — |
| config.checkTolerance | RUNTIME_PASS | — |
| config.sniffingTimeout | RUNTIME_PASS | — |
| config.lanInterface | RUNTIME_PASS | — |
| config.wanInterface | RUNTIME_PASS | — |
| config.udpCheckDns | RUNTIME_PASS | — |
| config.tcpCheckUrl | RUNTIME_PASS | — |
| config.dialMode | RUNTIME_PASS | — |
| config.tcpCheckHttpMethod | RUNTIME_PASS | — |
| config.disableWaitingNetwork | RUNTIME_PASS | — |
| config.autoConfigKernelParameter | RUNTIME_PASS | — |
| config.tlsImplementation | RUNTIME_PASS | — |
| config.utlsImitate | RUNTIME_PASS | — |
| config.tproxyPortProtect | FAIL | official DAE |
| config.soMarkFromDae | RUNTIME_PASS | — |
| config.mptcp | RUNTIME_PASS | — |
| config.enableLocalTcpFastRedirect | FAIL | official DAE |
| config.bandwidthMaxTx | RUNTIME_PASS | — |
| config.bandwidthMaxRx | RUNTIME_PASS | — |
| config.bootstrapResolver | RUNTIME_PASS | — |
| config.fallbackResolver | RUNTIME_PASS | — |
| node.v2ray.add | CONFIG_PASS | — |
| node.v2ray.aid | CONFIG_PASS | — |
| node.v2ray.allowInsecure | FAIL | official DAE |
| node.v2ray.alpn | CONFIG_PASS | — |
| node.v2ray.ech | FAIL | official DAE |
| node.v2ray.flow | CONFIG_PASS | — |
| node.v2ray.fp | CONFIG_PASS | — |
| node.v2ray.grpcAuthority | FAIL | official DAE |
| node.v2ray.grpcMode | FAIL | official DAE |
| node.v2ray.host | CONFIG_PASS | — |
| node.v2ray.id | CONFIG_PASS | — |
| node.v2ray.net | FAIL | official daed |
| node.v2ray.path | CONFIG_PASS | — |
| node.v2ray.pbk | CONFIG_PASS | — |
| node.v2ray.port | CONFIG_PASS | — |
| node.v2ray.pqv | FAIL | official DAE |
| node.v2ray.protocol | CONFIG_PASS | — |
| node.v2ray.ps | CONFIG_PASS | — |
| node.v2ray.scy | FAIL | official DAE |
| node.v2ray.sid | CONFIG_PASS | — |
| node.v2ray.sni | CONFIG_PASS | — |
| node.v2ray.spx | CONFIG_PASS | — |
| node.v2ray.tls | CONFIG_PASS | — |
| node.v2ray.type | CONFIG_PASS | — |
| node.v2ray.xhttpExtra | FAIL | official daed |
| node.v2ray.xhttpMode | FAIL | official daed |
| node.ss.host | CONFIG_PASS | — |
| node.ss.impl | FAIL | official DAE |
| node.ss.method | CONFIG_PASS | — |
| node.ss.mode | CONFIG_PASS | — |
| node.ss.name | CONFIG_PASS | — |
| node.ss.obfs | CONFIG_PASS | — |
| node.ss.password | CONFIG_PASS | — |
| node.ss.path | FAIL | official DAE |
| node.ss.plugin | CONFIG_PASS | — |
| node.ss.port | CONFIG_PASS | — |
| node.ss.server | CONFIG_PASS | — |
| node.ss.tls | CONFIG_PASS | — |
| node.ssr.method | CONFIG_PASS | — |
| node.ssr.name | CONFIG_PASS | — |
| node.ssr.obfs | CONFIG_PASS | — |
| node.ssr.obfsParam | CONFIG_PASS | — |
| node.ssr.password | CONFIG_PASS | — |
| node.ssr.port | CONFIG_PASS | — |
| node.ssr.proto | CONFIG_PASS | — |
| node.ssr.protoParam | CONFIG_PASS | — |
| node.ssr.server | CONFIG_PASS | — |
| node.trojan.allowInsecure | CONFIG_PASS | — |
| node.trojan.host | CONFIG_PASS | — |
| node.trojan.method | CONFIG_PASS | — |
| node.trojan.name | CONFIG_PASS | — |
| node.trojan.obfs | CONFIG_PASS | — |
| node.trojan.password | CONFIG_PASS | — |
| node.trojan.path | CONFIG_PASS | — |
| node.trojan.peer | CONFIG_PASS | — |
| node.trojan.port | CONFIG_PASS | — |
| node.trojan.server | CONFIG_PASS | — |
| node.trojan.ssCipher | CONFIG_PASS | — |
| node.trojan.ssPassword | CONFIG_PASS | — |
| node.tuic.allowInsecure | CONFIG_PASS | — |
| node.tuic.alpn | CONFIG_PASS | — |
| node.tuic.congestion_control | CONFIG_PASS | — |
| node.tuic.disable_sni | CONFIG_PASS | — |
| node.tuic.name | CONFIG_PASS | — |
| node.tuic.password | CONFIG_PASS | — |
| node.tuic.port | CONFIG_PASS | — |
| node.tuic.server | CONFIG_PASS | — |
| node.tuic.sni | CONFIG_PASS | — |
| node.tuic.udp_relay_mode | CONFIG_PASS | — |
| node.tuic.uuid | CONFIG_PASS | — |
| node.juicity.allowInsecure | CONFIG_PASS | — |
| node.juicity.congestion_control | CONFIG_PASS | — |
| node.juicity.name | CONFIG_PASS | — |
| node.juicity.password | CONFIG_PASS | — |
| node.juicity.pinned_certchain_sha256 | CONFIG_PASS | — |
| node.juicity.port | CONFIG_PASS | — |
| node.juicity.server | CONFIG_PASS | — |
| node.juicity.sni | CONFIG_PASS | — |
| node.juicity.uuid | CONFIG_PASS | — |
| node.hysteria2.allowInsecure | CONFIG_PASS | — |
| node.hysteria2.auth | CONFIG_PASS | — |
| node.hysteria2.name | CONFIG_PASS | — |
| node.hysteria2.pinSHA256 | CONFIG_PASS | — |
| node.hysteria2.port | CONFIG_PASS | — |
| node.hysteria2.ports | FAIL | official DAE |
| node.hysteria2.server | CONFIG_PASS | — |
| node.hysteria2.sni | CONFIG_PASS | — |
| node.anytls.allowInsecure | CONFIG_PASS | — |
| node.anytls.auth | CONFIG_PASS | — |
| node.anytls.name | CONFIG_PASS | — |
| node.anytls.port | CONFIG_PASS | — |
| node.anytls.server | CONFIG_PASS | — |
| node.anytls.sni | CONFIG_PASS | — |
| node.http.host | CONFIG_PASS | — |
| node.http.name | CONFIG_PASS | — |
| node.http.password | CONFIG_PASS | — |
| node.http.port | CONFIG_PASS | — |
| node.http.protocol | CONFIG_PASS | — |
| node.http.username | CONFIG_PASS | — |
| node.socks5.host | CONFIG_PASS | — |
| node.socks5.name | CONFIG_PASS | — |
| node.socks5.password | CONFIG_PASS | — |
| node.socks5.port | CONFIG_PASS | — |
| node.socks5.username | CONFIG_PASS | — |
| action.setJsonStorage | CONFIG_PASS | — |
| action.createConfig | CONFIG_PASS | — |
| action.updateConfig | CONFIG_PASS | — |
| action.removeConfig | CONFIG_PASS | — |
| action.selectConfig | CONFIG_PASS | — |
| action.renameConfig | RUNTIME_PASS | — |
| action.createRouting | CONFIG_PASS | — |
| action.updateRouting | RUNTIME_PASS | — |
| action.removeRouting | CONFIG_PASS | — |
| action.selectRouting | CONFIG_PASS | — |
| action.renameRouting | RUNTIME_PASS | — |
| action.createDns | RUNTIME_PASS | — |
| action.updateDns | CONFIG_PASS | — |
| action.removeDns | RUNTIME_PASS | — |
| action.selectDns | RUNTIME_PASS | — |
| action.renameDns | RUNTIME_PASS | — |
| action.createGroup | CONFIG_PASS | — |
| action.removeGroup | CONFIG_PASS | — |
| action.groupSetPolicy | RUNTIME_PASS | — |
| action.renameGroup | CONFIG_PASS | — |
| action.groupAddNodes | CONFIG_PASS | — |
| action.groupDelNodes | RUNTIME_PASS | — |
| action.groupAddSubscriptions | CONFIG_PASS | — |
| action.groupDelSubscriptions | CONFIG_PASS | — |
| action.importNodes | CONFIG_PASS | — |
| action.removeNodes | CONFIG_PASS | — |
| action.updateNode | RUNTIME_PASS | — |
| action.importSubscription | CONFIG_PASS | — |
| action.updateSubscription | RUNTIME_PASS | — |
| action.testNodeLatencies | RUNTIME_PASS | — |
| action.removeSubscriptions | CONFIG_PASS | — |
| action.run | RUNTIME_PASS | — |
| action.stop | RUNTIME_PASS | — |
| action.updateAvatar | RUNTIME_PASS | — |
| action.updateName | RUNTIME_PASS | — |
| action.updatePassword | RUNTIME_PASS | — |
| action.updateUsername | RUNTIME_PASS | — |
| action.tagNode | CONFIG_PASS | — |
| action.tagSubscription | RUNTIME_PASS | — |
| action.updateSubscriptionLink | RUNTIME_PASS | — |
| action.updateSubscriptionCron | FAIL | official daed |
| action.createUser | RUNTIME_PASS | — |
| action.token | RUNTIME_PASS | — |
| dns.name | RUNTIME_PASS | — |
| dns.editorMode | FAIL | official Web |
| dns.advancedText | RUNTIME_PASS | — |
| dns.upstream.add | CONFIG_PASS | — |
| dns.upstream.name | CONFIG_PASS | — |
| dns.upstream.link | CONFIG_PASS | — |
| dns.upstream.remove | CONFIG_PASS | — |
| dns.request.fallback | CONFIG_PASS | — |
| dns.request.add | CONFIG_PASS | — |
| dns.request.matcher | CONFIG_PASS | — |
| dns.request.target | CONFIG_PASS | — |
| dns.request.remove | CONFIG_PASS | — |
| dns.response.fallback | CONFIG_PASS | — |
| dns.response.add | CONFIG_PASS | — |
| dns.response.matcher | CONFIG_PASS | — |
| dns.response.target | CONFIG_PASS | — |
| dns.response.remove | CONFIG_PASS | — |
| routing.name | RUNTIME_PASS | — |
| routing.editorMode | CONFIG_PASS | — |
| routing.simplePreset | CONFIG_PASS | — |
| routing.macEnabled | CONFIG_PASS | — |
| routing.macAction | CONFIG_PASS | — |
| routing.macList | CONFIG_PASS | — |
| routing.advancedText | RUNTIME_PASS | — |
| subscription.link | RUNTIME_PASS | — |
| subscription.tag | RUNTIME_PASS | — |
| subscription.cronEnable | FAIL | official daed |
| subscription.cronExp | FAIL | official daed |
| group.name | CONFIG_PASS | — |
| group.policy | RUNTIME_PASS | — |
| group.nameFilterRegex | CONFIG_PASS | — |
| node.tag | CONFIG_PASS | — |
| account.username | RUNTIME_PASS | — |
| account.name | RUNTIME_PASS | — |
| account.avatar | RUNTIME_PASS | — |
| account.currentPassword | RUNTIME_PASS | — |
| account.newPassword | RUNTIME_PASS | — |
| account.confirmPassword | CONFIG_PASS | — |
| setup.endpoint | CONFIG_PASS | — |
| setup.signupUsername | RUNTIME_PASS | — |
| setup.signupPassword | RUNTIME_PASS | — |
| setup.loginUsername | RUNTIME_PASS | — |
| setup.loginPassword | RUNTIME_PASS | — |
| config.duplicate | CONFIG_PASS | — |
| dns.duplicate | CONFIG_PASS | — |
| routing.duplicate | CONFIG_PASS | — |
| browser.theme.mode | CONFIG_PASS | — |
| browser.theme.color | CONFIG_PASS | — |
| browser.language | CONFIG_PASS | — |
| browser.logout | CONFIG_PASS | — |
| browser.profile.select | CONFIG_PASS | — |
| browser.profile.update | CONFIG_PASS | — |
| browser.profile.save | CONFIG_PASS | — |
| browser.profile.rename | CONFIG_PASS | — |
| browser.profile.remove | CONFIG_PASS | — |
| browser.group.collapse | CONFIG_PASS | — |
| browser.group.sectionCollapse | CONFIG_PASS | — |
| browser.picker.search | CONFIG_PASS | — |
| browser.picker.selection | CONFIG_PASS | — |
| browser.node.revealLink | CONFIG_PASS | — |
| browser.subscription.revealLink | CONFIG_PASS | — |
| browser.resource.copyLink | CONFIG_PASS | — |
| browser.order.group | CONFIG_PASS | — |
| browser.order.node | CONFIG_PASS | — |
| browser.order.subscription | CONFIG_PASS | — |
| browser.order.groupNodes | CONFIG_PASS | — |
| browser.order.groupSubscriptions | CONFIG_PASS | — |
| limitation.TRAFFIC_OVERVIEW | KNOWN_LIMITATION | — |
| limitation.SETUP_REMOUNT | KNOWN_LIMITATION | — |

## Retained upstream failures

### config.tproxyPortProtect

Owner: official DAE. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

Stored into control-plane field with no runtime read consumer. Locked source proof; no fictitious traffic differential.

Source evidence:
- https://github.com/daeuniverse/dae `dbae2e82d3ed5324e1648548720f8bbc8cde3882` — `control/control_plane.go`, lines [107, 878].

Runtime evidence: {"control": "config.tproxyPortProtect", "file": "additional-source-failures.json"}.

### config.enableLocalTcpFastRedirect

Owner: official DAE. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

Official model explicitly deprecated: not used. True readback, candidate, validation and running apply; source proves no implementation, not a performance benchmark.

Source evidence:
- https://github.com/daeuniverse/dae `dbae2e82d3ed5324e1648548720f8bbc8cde3882` — `config/config.go`, lines [38, 39].

Runtime evidence: {"case": "enableLocalTcpFastRedirect:true", "file": "../../continuation-2/evidence/global-continuation.json"}.

### node.v2ray.allowInsecure

Owner: official DAE. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

ParseVlessURL assigns AllowInsecure false; does not read submitted flag. Global option is ORed later, not a per-node equivalent. Official URI readback, candidate, validate/apply are recorded; ignored-field conclusion is locked parser/constructor evidence, not an unperformed protocol handshake.

Source evidence:
- https://github.com/olicesx/outbound `cc86ced2e683` — `dialer/v2ray/v2ray.go`, lines [337, 337].

Runtime evidence: {"case": "vless-grpc", "file": "node-continuation.json"}.

### node.v2ray.ech

Owner: official DAE. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

Official generated URL includes ech/pqv, but ParseVlessURL does not read either and V2Ray model has neither field. Official URI readback, candidate, validate/apply are recorded; ignored-field conclusion is locked parser/constructor evidence, not an unperformed protocol handshake.

Source evidence:
- https://github.com/olicesx/outbound `cc86ced2e683` — `dialer/v2ray/v2ray.go`, lines [317, 364].

Runtime evidence: {"case": "vless-grpc", "file": "node-continuation.json"}.

### node.v2ray.grpcAuthority

Owner: official DAE. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

Official form emits mode/authority; parser only reads serviceName and grpc constructor does not receive mode/authority. Official URI readback, candidate, validate/apply are recorded; ignored-field conclusion is locked parser/constructor evidence, not an unperformed protocol handshake.

Source evidence:
- https://github.com/olicesx/outbound `cc86ced2e683` — `dialer/v2ray/v2ray.go`, lines [216, 230, 348, 350].

Runtime evidence: {"case": "vless-grpc", "file": "node-continuation.json"}.

### node.v2ray.grpcMode

Owner: official DAE. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

Official form emits mode/authority; parser only reads serviceName and grpc constructor does not receive mode/authority. Official URI readback, candidate, validate/apply are recorded; ignored-field conclusion is locked parser/constructor evidence, not an unperformed protocol handshake.

Source evidence:
- https://github.com/olicesx/outbound `cc86ced2e683` — `dialer/v2ray/v2ray.go`, lines [216, 230, 348, 350].

Runtime evidence: {"case": "vless-grpc", "file": "node-continuation.json"}.

### node.v2ray.net

Owner: official daed. Locked version: official daed v2.1.1; wing dc503088945812c11235b35362d2bfa1a4c3bdf0.

net control fails for xhttp specifically; successful grpc/ws/tcp cases are retained

Source evidence:
- official wing `dc503088945812c11235b35362d2bfa1a4c3bdf0` — `db/node_utils.go`, lines [17, 33].

Runtime evidence: xhttp-diagnostic.json: actual importNodes response unexpected field: network: xhttp; source and applied configuration restored.

### node.v2ray.pqv

Owner: official DAE. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

Official generated URL includes ech/pqv, but ParseVlessURL does not read either and V2Ray model has neither field. Official URI readback, candidate, validate/apply are recorded; ignored-field conclusion is locked parser/constructor evidence, not an unperformed protocol handshake.

Source evidence:
- https://github.com/olicesx/outbound `cc86ced2e683` — `dialer/v2ray/v2ray.go`, lines [317, 364].

Runtime evidence: {"case": "vless-reality", "file": "node-continuation.json"}.

### node.v2ray.scy

Owner: official DAE. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

V2Ray JSON model has no scy; Dialer uses getAutoCipher() instead of submitted cipher. Official URI readback, candidate, validate/apply are recorded; ignored-field conclusion is locked parser/constructor evidence, not an unperformed protocol handshake.

Source evidence:
- https://github.com/olicesx/outbound `cc86ced2e683` — `dialer/v2ray/v2ray.go`, lines [33, 54, 302, 309].

Runtime evidence: {"case": "vmess-ws", "file": "node-continuation.json"}.

### node.v2ray.xhttpExtra

Owner: official daed. Locked version: official daed v2.1.1; wing dc503088945812c11235b35362d2bfa1a4c3bdf0.

net control fails for xhttp specifically; successful grpc/ws/tcp cases are retained

Source evidence:
- official wing `dc503088945812c11235b35362d2bfa1a4c3bdf0` — `db/node_utils.go`, lines [17, 33].

Runtime evidence: xhttp-diagnostic.json: actual importNodes response unexpected field: network: xhttp; source and applied configuration restored.

### node.v2ray.xhttpMode

Owner: official daed. Locked version: official daed v2.1.1; wing dc503088945812c11235b35362d2bfa1a4c3bdf0.

net control fails for xhttp specifically; successful grpc/ws/tcp cases are retained

Source evidence:
- official wing `dc503088945812c11235b35362d2bfa1a4c3bdf0` — `db/node_utils.go`, lines [17, 33].

Runtime evidence: xhttp-diagnostic.json: actual importNodes response unexpected field: network: xhttp; source and applied configuration restored.

### node.ss.impl

Owner: official DAE. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

The official UI emits impl; Sip003Opts/ParseSip003Opts have no consumer. Readback/validate/apply plus pinned parser audit; no protocol handshake claim.

Source evidence:
- https://github.com/olicesx/outbound `cc86ced2e683` — `dialer/shadowsocks/shadowsocks.go`, lines [361, 404].

Runtime evidence: {"cases": ["ss-websocket", "ss-simpleobfs"], "file": "node-continuation.json"}.

### node.ss.path

Owner: official DAE. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

v2ray-plugin websocket constructor replaces submitted path with literal slash. Saved /fixture URI applies, but pinned transport constructor uses /. No new protocol server.

Source evidence:
- https://github.com/olicesx/outbound `cc86ced2e683` — `dialer/shadowsocks/shadowsocks.go`, lines [95, 101].

Runtime evidence: {"case": "ss-websocket", "file": "node-continuation.json"}.

### node.hysteria2.ports

Owner: official DAE. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

Submitted ports option has no read consumer in ParseHysteria2URL. URI/config chain and parser audit; does not claim observed multi-port hopping.

Source evidence:
- https://github.com/olicesx/outbound `cc86ced2e683` — `dialer/hysteria2/hysteria2.go`, lines [161, 246].

Runtime evidence: {"case": "hysteria2", "file": "node-continuation.json"}.

### action.updateSubscriptionCron

Owner: official daed. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

Scheduler is restarted before deferred transaction commit and reads prior cron expression. Actual official mutation/readback and natural 90-second endpoint/journal observation; no scheduled fetch, old expression logged.

Source evidence:
- https://github.com/daeuniverse/dae-wing `dc503088945812c11235b35362d2bfa1a4c3bdf0` — `graphql/service/subscription/mutation_utils.go`, lines [190, 235, 435, 485].

Runtime evidence: {"case": "subscription.cron-enable-expression-disable", "diagnosis": "subscription-cron-diagnosis.json", "file": "subscription-continuation.json"}.

### dns.editorMode

Owner: official Web. Locked version: v1.28 b3043aa7ce07c774c65e546112aa2c7a1c12edb5.

Simple-mode direct submit/readback passes; mode-switch loses unsaved values

Source evidence:
- official daed Web `b3043aa7ce07c774c65e546112aa2c7a1c12edb5` — `apps/web/src/components/DNSFormModal/DNSForm.tsx`, lines [55, 70].

Runtime evidence: browser.json: simple mode added matrix_aux and rules; advanced editor displayed only prior source; returning to simple removed unsaved edits.

### subscription.cronEnable

Owner: official daed. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

Scheduler is restarted before deferred transaction commit and reads prior cron expression. Actual official mutation/readback and natural 90-second endpoint/journal observation; no scheduled fetch, old expression logged.

Source evidence:
- https://github.com/daeuniverse/dae-wing `dc503088945812c11235b35362d2bfa1a4c3bdf0` — `graphql/service/subscription/mutation_utils.go`, lines [190, 235, 435, 485].

Runtime evidence: {"case": "subscription.cron-enable-expression-disable", "diagnosis": "subscription-cron-diagnosis.json", "file": "subscription-continuation.json"}.

### subscription.cronExp

Owner: official daed. Locked version: {"DAE": "v2.1.1", "daed": "v2.1.1", "web": "v1.28"}.

Scheduler is restarted before deferred transaction commit and reads prior cron expression. Actual official mutation/readback and natural 90-second endpoint/journal observation; no scheduled fetch, old expression logged.

Source evidence:
- https://github.com/daeuniverse/dae-wing `dc503088945812c11235b35362d2bfa1a4c3bdf0` — `graphql/service/subscription/mutation_utils.go`, lines [190, 235, 435, 485].

Runtime evidence: {"case": "subscription.cron-enable-expression-disable", "diagnosis": "subscription-cron-diagnosis.json", "file": "subscription-continuation.json"}.
