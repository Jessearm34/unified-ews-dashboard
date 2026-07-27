<script>
	let { presets = [], current = 'ytd', onChange } = $props();
</script>

<div class="controls">
	<span class="lbl">Range:</span>
	{#each presets as [key, label] (key)}
		<button
			class="preset"
			class:active={current === key}
			onclick={() => onChange?.(key)}
		>{label}</button>
	{/each}
</div>