import {createReadStream, cpSync, existsSync, statSync} from 'node:fs';
import {extname, join, resolve} from 'node:path';
import {defineConfig, type Plugin} from 'vite';

const IMG_DIR = resolve(import.meta.dirname, '..', 'img');

const MIME: Record<string, string> = {
  '.webp': 'image/webp',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.svg': 'image/svg+xml',
};

/**
 * The about page renders the repository README, which links to the screenshots
 * in `<repo>/img`. That directory lives outside the Vite root, so it is served
 * from there in dev and copied into the bundle on build.
 */
function repoImages(): Plugin {
  let outDir = 'dist';
  return {
    name: 'mapant-repo-images',
    configResolved(config) {
      outDir = config.build.outDir;
    },
    configureServer(server) {
      server.middlewares.use('/img', (req, res, next) => {
        const name = decodeURIComponent((req.url ?? '').split('?')[0].replace(/^\//, ''));
        const file = join(IMG_DIR, name);
        if (!name || name.includes('..') || !existsSync(file) || !statSync(file).isFile()) {
          next();
          return;
        }
        res.setHeader('Content-Type', MIME[extname(file).toLowerCase()] ?? 'application/octet-stream');
        createReadStream(file).pipe(res);
      });
    },
    closeBundle() {
      if (existsSync(IMG_DIR)) {
        cpSync(IMG_DIR, resolve(import.meta.dirname, outDir, 'img'), {recursive: true});
      }
    },
  };
}

// Served from a custom domain (mapant.orienteering-allgaeu.de), so assets live at the root.
export default defineConfig({
  base: '/',
  plugins: [repoImages()],
  build: {
    rollupOptions: {
      // Two pages, no client-side routing: /index.html and /about.html.
      input: {index: 'index.html', about: 'about.html'},
    },
  },
  server: {
    // The about page imports the repository README, which sits above the Vite root.
    // The build inlines it; only the dev server needs to be allowed to read it.
    fs: {allow: ['..']},
  },
});
