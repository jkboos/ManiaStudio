// Upstream's public prism.ts contains declarations, not its native runtime.
// Pattern geometry needs only the documented 6K-8K routing flag. Native MSD
// calls are deliberately unavailable, rather than replaced by invented values.
export const PRISM_KEY_COUNTS=new Set([6,7,8]);
export const PRISM_ENABLED=true;
export const usesPrism=keys=>PRISM_KEY_COUNTS.has(Number(keys));
export function prismLnLeadValues() {throw new Error('Native Prism MSD is not part of the offline pattern-feature adapter');}
