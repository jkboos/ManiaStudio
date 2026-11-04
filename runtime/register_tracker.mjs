// Resolve extensionless relative TypeScript imports without editing upstream.
import {registerHooks} from 'node:module';
registerHooks({resolve(specifier,context,nextResolve) {
  if (specifier.startsWith('.') && context.parentURL && /\/algorithms\/msd\/prism(?:\.ts)?$/.test(new URL(specifier,context.parentURL).pathname)) {
    return {url:new URL('./tracker_prism_flags.mjs',import.meta.url).href,shortCircuit:true};
  }
  try {return nextResolve(specifier,context);}
  catch(error) {
    if (specifier.startsWith('.') && !/\.[a-z]+$/i.test(specifier)) return nextResolve(specifier+'.ts',context);
    throw error;
  }
}});
