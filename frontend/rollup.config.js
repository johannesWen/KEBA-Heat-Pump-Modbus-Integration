import resolve from '@rollup/plugin-node-resolve';
import terser from '@rollup/plugin-terser';
import { readFileSync } from 'fs';
import { dirname, resolve as pathResolve } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const manifestPath = pathResolve(
  __dirname,
  '../custom_components/keba_heat_pump_modbus/manifest.json',
);
let manifestVersion = '0.0.0';
try {
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  manifestVersion = manifest.version || manifestVersion;
} catch (err) {
  console.warn('Could not read manifest version:', err.message);
}

/** Rollup plugin that exposes the integration version as a virtual module. */
const integrationVersionPlugin = () => ({
  name: 'integration-version',
  resolveId(source) {
    if (source === 'virtual:integration-version') {
      return source;
    }
    return null;
  },
  load(id) {
    if (id === 'virtual:integration-version') {
      return `export const CARD_VERSION = ${JSON.stringify(manifestVersion)};`;
    }
    return null;
  },
});

export default {
  input: 'src/keba-heat-pump-modbus-card.js',
  output: {
    file: '../custom_components/keba_heat_pump_modbus/static/keba-heat-pump-modbus-card.js',
    format: 'es',
    inlineDynamicImports: true,
  },
  plugins: [
    integrationVersionPlugin(),
    resolve(),
    terser(),
  ],
};
