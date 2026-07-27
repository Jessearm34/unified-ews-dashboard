<script>
	import { onMount } from 'svelte';

	let { html = '', title = '' } = $props();

	let container;
	let chartId = $derived(`chart-${Math.random().toString(36).slice(2, 9)}`);

	onMount(() => {
		if (!html || !container) return;
		// Remove any existing script tags from html and insert into DOM
		const div = document.createElement('div');
		div.innerHTML = html;
		// Move all child nodes (including plot divs) into container
		container.innerHTML = '';
		const plotDiv = div.querySelector('.js-plotly-plot');
		if (plotDiv) {
			container.appendChild(plotDiv);
		} else {
			// Fallback: insert all content
			while (div.firstChild) {
				container.appendChild(div.firstChild);
			}
		}
		// Re-execute any inline scripts if needed
		div.querySelectorAll('script').forEach(s => {
			const ns = document.createElement('script');
			for (const attr of s.attributes) ns.setAttribute(attr.name, attr.value);
			ns.textContent = s.textContent;
			document.head.appendChild(ns);
		});
	});
</script>

<div class="panel">
	<h3>{title}</h3>
	<div bind:this={container} class="chart-container"></div>
</div>