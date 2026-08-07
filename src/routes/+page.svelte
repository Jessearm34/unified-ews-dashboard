<script>
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { fetchOverview } from '$lib/api.js';
	import { loading, error, lastRefresh, viewData } from '$lib/stores/dashboard.js';
	import KPICard from '$lib/components/KPICard.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import PlotlyChart from '$lib/components/PlotlyChart.svelte';
	import RangeControl from '$lib/components/RangeControl.svelte';

	let data = $state(null);
	let isLoading = $state(true);
	let errMsg = $state(null);
	let range = $state('ytd');
	let autoRefresh = $state(true);
	let refreshInterval = $state(null);
	let compare = $state(false);

	const rangePresets = [['ytd','YTD'],['lm','Last month'],['30d','30d'],['90d','90d'],['ly','Last year'],['all','All']];

	async function load(rangeKey = range, silent = false) {
		if (!silent) isLoading = true;
		errMsg = null;
		try {
			const result = await fetchOverview(rangeKey, compare);
			if (result.redirect) {
				goto(result.redirect);
				return;
			}
			data = result;
			lastRefresh.set(new Date());
		} catch (e) {
			errMsg = e.message;
			if (!silent) data = null;
		} finally {
			if (!silent) isLoading = false;
			loading.set(false);
			error.set(errMsg);
			viewData.set(data);
		}
	}

	function onRangeChange(key) {
		range = key;
		load(key);
	}

	function toggleCompare() {
		compare = !compare;
		load(range);
	}

	onMount(() => {
		load('ytd');
		// Auto-poll every 60 seconds for constant data updates
		refreshInterval = setInterval(() => load(range, true), 60000);
	});

	onDestroy(() => {
		if (refreshInterval) clearInterval(refreshInterval);
	});
</script>

<svelte:head>
	<title>EWS Unified Dashboard — Overview</title>
</svelte:head>

<div class="header">
	<h1>Overview</h1>
	<div class="refreshed">
		<span class="pill">
			<span class="dot" class:stale={isLoading}></span>
			{isLoading ? 'Loading...' : data ? `Updated ${new Date(data.loaded_at).toLocaleTimeString()}` : 'Not loaded'}
		</span>
	</div>
</div>

<RangeControl presets={rangePresets} {range} onChange={onRangeChange} />

{#if data?.range_info}
	<span class="note">Showing {data.range_info}</span>
{/if}

{#if isLoading}
	<div class="loading"><span class="spinner"></span> Loading dashboard data...</div>
{:else if errMsg}
	<div class="chart-empty">{errMsg}</div>
{:else if data}
	<!-- KPI Groups -->
	{#if data.kpis?.length}
		{#if data.kpis.filter(k => k.platform === 'QB').length}
			<div class="kpi-group">
				<div class="kpi-group-title">QuickBooks <span class="line"></span></div>
				<div class="kpis">
					{#each data.kpis.filter(k => k.platform === 'QB') as kpi (kpi.label)}
						<KPICard {...kpi} deltaUpGood={kpi.delta_up_good ?? true} />
					{/each}
				</div>
			</div>
		{/if}
		{#if data.kpis.filter(k => k.platform === 'SD').length}
			<div class="kpi-group">
				<div class="kpi-group-title">SiteDocs <span class="line"></span></div>
				<div class="kpis">
					{#each data.kpis.filter(k => k.platform === 'SD') as kpi (kpi.label)}
						<KPICard {...kpi} deltaUpGood={kpi.delta_up_good ?? true} />
					{/each}
				</div>
			</div>
		{/if}
	{/if}

	<!-- Charts -->
	{#if data.charts && Object.keys(data.charts).length}
		<div class="charts-grid two">
			{#each Object.entries(data.charts) as [id, chart] (id)}
				<PlotlyChart html={chart.html} title={chart.title} />
			{/each}
		</div>
	{/if}
{/if}
