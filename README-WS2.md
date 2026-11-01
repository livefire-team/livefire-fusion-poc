# WS2 starter files (LiveFire Fusion: referee, fault and lab)

Files from the "WS2 Build Guide to G1", collected Oct 27, with three additions:
- scripts/reset.sh, written from the guide's four-step description.
- scripts/drill.sh, which runs one manual drill and prints the referee's result at each stage.
- infra/main.bicep: WS1's three outputs, the principalType and refresh pass-throughs, and the Path A deny policy
  and limited recovery role behind PATH_A_CONTROLS=on (off by default). control.bicep now outputs both identities.

As tested here: every script passes bash -n and ShellCheck; three drill.sh runs against a fake Azure finished with a
complete event log; fault.sh refuses a resource group that isn't a twin; infra/main.bicep compiles with no lint
warnings, with PATH_A_CONTROLS on or off.
Not yet verified here: anything against the real lab, and the referee Dockerfile build (G2).

infra/modules/twin.bicep is WS1's file, included only so main.bicep compiles. Unzip with -n.
Contracts (referee result, Ops actions, event format) now live in WS4's contracts/ folder.
