import './register_tracker.mjs';
import fs from 'node:fs';
import crypto from 'node:crypto';
const {parseManiaBeatmap}=await import('./third_party/mania_tracker/algorithms/chart/beatmap.ts');
const {analyzeManiaPatterns}=await import('./third_party/mania_tracker/algorithms/dan-estimator/patterns.ts');

export const AXES=['speed','stamina','tech','jack','stream','LN'];
export function analyzeTechniques(text) {
  const map=parseManiaBeatmap(text);
  if (![4,7].includes(map.keyCount) || map.notes.length<2) throw new Error('Need a nonempty 4K/7K mania chart');
  const report=analyzeManiaPatterns(map,{rate:1});
  const scores=Object.fromEntries(report.allPatterns.map(p=>[p.id,p.score]));
  const maxScore=ids=>Math.max(0,...ids.map(id=>scores[id]??0));
  const m=report.metrics;
  const raw={speed:m.rowBurstPressure,stamina:m.sustainedNps30s,tech:scores.tech??0,
    jack:maxScore(['jack','chordjack','speedjack','handjack']),
    stream:maxScore(['stream','dumpstream','jumpstream','handstream','quadstream','chordstream','bracket']),
    LN:m.holdRatio};
  if (!Object.values(raw).every(Number.isFinite)) throw new Error('Nonfinite technique feature');
  return {keys:map.keyCount,object_count:map.notes.length,raw,patterns:report.allPatterns,
    primary:report.primary,metrics:m,warnings:report.warnings,
    definition:{speed:'rowBurstPressure (upstream geometric burst-pressure feature; not MSD Speed)',
      stamina:'sustainedNps30s (30-second sustained note rate; not MSD Stamina)',
      tech:'upstream tech score',jack:'max of jack/chordjack/speedjack/handjack scores',
      stream:'max of flow-pattern scores, including Jumpstream/Handstream and 7K Bracket',LN:'hold note fraction'}};
}
export function analyzeFile(path) {
  const bytes=fs.readFileSync(path);
  return {...analyzeTechniques(bytes.toString('utf8').replace(/^\uFEFF/,'')),osu_sha256:crypto.createHash('sha256').update(bytes).digest('hex')};
}
