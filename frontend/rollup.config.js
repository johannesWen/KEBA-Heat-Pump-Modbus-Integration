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
let integrationDomain = 'keba_heat_pump_modbus';
try {
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  manifestVersion = manifest.version || manifestVersion;
  integrationDomain = manifest.domain || integrationDomain;
} catch (err) {
  console.warn('Could not read manifest version:', err.message);
}

/** Expose integration metadata to the bundled card. */
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
      return `export const CARD_VERSION = ${JSON.stringify(manifestVersion)};\nexport const INTEGRATION_DOMAIN = ${JSON.stringify(integrationDomain)};`;
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
