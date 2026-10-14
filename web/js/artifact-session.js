// A partial build's panel list is not an inventory of all valid artifacts.
export function monitorSession(artifact, manifest) {
  if (artifact?.unavailable) return { ok: false, reason: 'Monitor measurements are unavailable in this artifact; no queue is substituted.' };
  if (manifest?.errors?.monitor) return { ok: false, reason: 'The monitor builder failed for this session; its previous file is not used.' };
  if (!artifact?.as_of || !manifest?.as_of || artifact.as_of !== manifest.as_of) return { ok: false, reason: `Monitor date ${artifact?.as_of || 'unknown'} does not match session ${manifest?.as_of || 'unknown'}; stale queues are not used.` };
  return { ok: true, partial: !manifest.panels?.includes('monitor') };
}
