<script>
	let { title, dot = '#2563eb', scroll = false, children } = $props();
</script>

<div class="panel" class:panel-scroll={scroll}>
	<h3><span class="dot" style="background: {dot}"></span>{title}</h3>
	{@render children?.()}
</div>