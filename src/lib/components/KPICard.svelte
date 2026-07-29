<script>
	import { formatValue, ragColor } from '$lib/stores/dashboard.js';

	let { label, value, unit = '', hint = '', rag = null, platform = '', delta = null, deltaUpGood = true, help = '', deltaLabel = '' } = $props();

	const formatted = $derived(formatValue(value, unit));
	const deltaClass = $derived(delta != null ? (delta > 0 ? (deltaUpGood ? 'up' : 'down') : deltaUpGood ? 'down' : 'up') : '');
</script>

<div class="kpi">
	<div class="k-label">
		{#if rag}
			<span class="kpi-rag" style="background: {ragColor(rag)}"></span>
		{/if}
		{label}
		{#if help}
			<span class="k-tip-icon" title={help}>ⓘ</span>
		{/if}
		{#if platform}
			<span class="k-platform">{platform}</span>
		{/if}
	</div>
	<div class="k-value">
		{formatted}
		{#if delta != null}
			<span class="k-delta {deltaClass}">{delta > 0 ? '▲' : '▼'} {Math.abs(delta).toFixed(1)}% {deltaLabel}</span>
		{/if}
	</div>
	{#if hint}
		<div class="k-hint">{hint}</div>
	{/if}
</div>
