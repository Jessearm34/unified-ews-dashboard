<script>
	import { onMount } from 'svelte';

	let { html = '', title = '' } = $props();

	let container;

	onMount(() => {
		if (!html || !container) return;

		// Parse the chart HTML into a temp element
		const temp = document.createElement('div');
		temp.innerHTML = html;

		// Grab scripts BEFORE moving children (they get moved too)
		const scripts = Array.from(temp.querySelectorAll('script'));

		// Find the plot div — support both old (.js-plotly-plot) and new (.plotly-graph-div) Plotly classes
		const plotDiv = temp.querySelector('.js-plotly-plot, .plotly-graph-div');

		// Clear container and insert the plot div
		container.innerHTML = '';
		if (plotDiv) {
			container.appendChild(plotDiv);
		} else {
			// Fallback: move all content
			while (temp.firstChild) {
				container.appendChild(temp.firstChild);
			}
		}

		// Execute scripts — Plotly.newPlot targets the div by ID which is now in the DOM
		scripts.forEach((s) => {
			const ns = document.createElement('script');
			for (const attr of s.attributes) ns.setAttribute(attr.name, attr.value);
			ns.textContent = s.textContent;
			container.appendChild(ns);
		});
	});
</script>

<div class="panel">
	<h3>{title}</h3>
	<div bind:this={container} class="chart-container"></div>
</div>