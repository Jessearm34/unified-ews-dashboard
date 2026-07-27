import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			'/api': 'http://localhost:8000',
			'/login': 'http://localhost:8000',
			'/logout': 'http://localhost:8000',
			'/health': 'http://localhost:8000'
		}
	}
});