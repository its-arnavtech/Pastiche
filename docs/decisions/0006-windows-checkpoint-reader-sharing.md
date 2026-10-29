# 0006 Retry transient Windows checkpoint sharing failures

Context: the ten-minute NPU run completed, but the following iGPU baseline stopped
at 248 seconds when replacing GPU-checkpoint.json raised WinError 5. A concurrent
read of the checkpoint can hold a Windows handle without delete sharing. Audio
and the completed NPU benchmark were unaffected.

Decision: atomic replacements retry PermissionError for up to about nine seconds
with bounded backoff. Writers still replace only after closing the complete
temporary file. Apply the helper to JSON, manifests and generated audio. Restart
the incomplete iGPU/CPU baseline; retain and report the earlier completed NPU run.
Monitoring should read/close files promptly rather than keep handles open.

Alternatives: abandon atomicity, swallow all checkpoint failures, or disable the
reader/antivirus. These either risk partial state or change the machine unnecessarily.

Consequences: the transient sharing race is covered by a regression test. Persistent
permission failures remain errors. No source audio or system configuration changes.
