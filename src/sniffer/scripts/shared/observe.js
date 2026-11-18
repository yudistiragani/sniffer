// Harmless loader example, not a network hook, CA installer, or TLS/pinning bypass.
send({type: "instrumentation_ready", pid: Process.id, arch: Process.arch});
