<script>
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
		import { fetchQB, fetchSD, fetchGT, fetchIN } from '$lib/api.js';
	import { platform, section, platforms } from '$lib/stores/dashboard.js';
	import KPICard from '$lib/components/KPICard.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import PlotlyChart from '$lib/components/PlotlyChart.svelte';
	import RangeControl from '$lib/components/RangeControl.svelte';

	let { data: routeData } = $props();

	let data = $state(null);
	let isLoading = $state(true);
	let errMsg = $state(null);
	let currentPlatform = $state('');
	let currentSection = $state('');
	let refreshInterval = $state(null);

	const rangePresets = [['ytd','YTD'],['lm','Last month'],['30d','30d'],['90d','90d'],['ly','Last year'],['all','All']];
	const qbRangePresets = [...rangePresets];
	const qbBasisOptions = [['accrual','Accrual'],['cash','Cash']];

	let range = $state('all');
	let basis = $state('accrual');
	let compare = $state(false);
	let pageTitle = $state('');

	async function load() {
		isLoading = true;
		errMsg = null;
		const plat = routeData?.params?.platform || $page.params.platform;
		const sec = routeData?.params?.section || $page.params.section || 'overview';

		currentPlatform = plat;
		currentSection = sec;
		platform.set(plat);
		section.set(sec);

		// Resolve human-readable title from the registry
		const pf = platforms.find(p => p.key === plat);
		const sf = pf?.sections.find(s => s.key === sec);
		pageTitle = sf?.label || `${plat.toUpperCase()}: ${sec}`;

		try {
			let result;
			if (plat === 'qb') {
				result = await fetchQB(sec, { basis, range });
			} else if (plat === 'sd') {
				result = await fetchSD(sec, compare);
						} else if (plat === 'gt') {
							result = await fetchGT(sec, range);
						} else if (plat === 'in') {
							result = await fetchIN(sec);
			} else {
				throw new Error('Unknown platform');
			}
			if (result?.redirect) {
				goto(result.redirect);
				return;
			}
			data = result;
		} catch (e) {
			errMsg = e.message;
			data = null;
		} finally {
			isLoading = false;
		}
	}

	function onRangeChange(key) {
		range = key;
		load();
	}

	function toggleCompare() {
		compare = !compare;
		load();
	}

	// Reload when platform params change
	$effect(() => {
		const p = routeData?.params?.platform || $page.params.platform;
		const s = routeData?.params?.section || $page.params.section;
		if (p) load();
	});

	// Auto-poll every 60 seconds for constant data updates
	onMount(() => {
		refreshInterval = setInterval(() => load(), 60000);
	});
	onDestroy(() => {
		if (refreshInterval) clearInterval(refreshInterval);
	});
</script>

<svelte:head>
	<title>EWS — {pageTitle}</title>
</svelte:head>

<div class="header">
	<h1>{pageTitle}</h1>
	<div class="refreshed">
		<span class="pill">
			<span class="dot" class:stale={isLoading}></span>
			{isLoading ? 'Loading...' : data ? `Updated ${new Date(data.loaded_at || Date.now()).toLocaleTimeString()}` : ''}
		</span>
	</div>
</div>

{#if currentPlatform === 'qb'}
	<RangeControl presets={qbRangePresets} {range} onChange={onRangeChange} />
	{#if basis}
		<div class="controls" style="margin-top: 0;">
			<span class="lbl">Basis:</span>
			{#each qbBasisOptions as [key, label] (key)}
				<button
					class="preset"
					class:active={basis === key}
					onclick={() => { basis = key; load(); }}
				>{label}</button>
			{/each}
		</div>
	{/if}
{:else if currentPlatform === 'gt'}
	<RangeControl presets={rangePresets} {range} onChange={onRangeChange} />
{/if}

{#if currentPlatform === 'sd'}
	<div class="controls" style="margin-top:0">
		<button class="preset" class:active={compare} onclick={toggleCompare}>
			{compare ? '◉' : '○'} Compare
		</button>
	</div>
{/if}

{#if data?.range_info}
	<div class="note" style="margin-bottom:14px">Showing {data.range_info}</div>
{/if}

{#if isLoading}
	<div class="loading"><span class="spinner"></span> Loading...</div>
{:else if errMsg}
	<div class="chart-empty">{errMsg}</div>
{:else if data}
	<!-- KPIs -->
	{#if data.kpis?.length}
		<div class="kpis">
			{#each data.kpis as kpi (kpi.label)}
				<KPICard {...kpi} deltaUpGood={kpi.delta_up_good ?? true} />
			{/each}
		</div>
	{/if}

	<!-- Charts grid -->
	{#if data.charts && Object.keys(data.charts).length}
		{@const entries = Object.entries(data.charts)}
		{@const count = entries.length}
		<div class="charts-grid two" class:single={count === 1}>
			{#each entries as [id, chart] (id)}
				<PlotlyChart html={chart.html} title={chart.title} />
			{/each}
		</div>
	{/if}
{/if}
