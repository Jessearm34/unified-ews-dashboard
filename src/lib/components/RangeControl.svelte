<script>
	let { presets = [], range = 'ytd', onChange } = $props();
</script>

<div class="controls">
	<span class="lbl">Range:</span>
	{#each presets as [key, label] (key)}
		<button
			class="preset"
			class:active={range === key}
			onclick={() => onChange?.(key)}
		>{label}</button>
	{/each}
</div>