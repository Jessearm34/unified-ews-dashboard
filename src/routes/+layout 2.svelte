<script>
	import '../app.css';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import { page } from '$app/stores';
	import { platform } from '$lib/stores/dashboard.js';
	import { onMount } from 'svelte';

	let { children } = $props();

	onMount(() => {
		// Sync stores with URL on page load
		const url = $page.url;
		const p = url.pathname.split('/').filter(Boolean);
		if (p.length >= 2) {
			platform.set(p[0]);
		} else {
			platform.set('overview');
		}
	});
</script>

<div class="app-layout">
	<Sidebar />
	<main class="main">
		{@render children?.()}
	</main>
</div>