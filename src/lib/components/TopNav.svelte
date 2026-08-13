<script>
	import { platform as activePlatform, section as activeSection, platforms } from '$lib/stores/dashboard.js';
	import { goto } from '$app/navigation';

	let currentPlatform = $derived($activePlatform);
	let currentSection = $derived($activeSection);

	function navigateTo(plat, sec) {
		if (plat) {
			activePlatform.set(plat);
			activeSection.set(sec);
			goto(`/${plat}/${sec}`);
		} else {
			activePlatform.set('overview');
			activeSection.set('overview');
			goto('/');
		}
	}
</script>

<header class="topnav">
	<a class="logo" onclick={() => navigateTo(null, null)} role="button" tabindex="0" href="/">EWS<span> Dashboard</span></a>
	<nav>
		<button class="tn-link" class:active={currentPlatform === 'overview'}
			onclick={() => navigateTo(null, null)}>Overview</button>
		<span class="tn-sep"></span>
		{#each platforms as pf (pf.key)}
			<button class="tn-link" class:active={currentPlatform === pf.key}
				onclick={() => navigateTo(pf.key, pf.sections[0].key)}>{pf.label}</button>
		{/each}
	</nav>
				<div class="right">
					<span class="dot"></span> Live
				</div>
</header>

{#if currentPlatform && currentPlatform !== 'overview'}
	{@const pf = platforms.find(p => p.key === currentPlatform)}
	<div class="subnav">
		{#if pf}
			{#each pf.sections as sec (sec.key)}
				<button class="tn-link" class:active={currentSection === sec.key}
					onclick={() => navigateTo(pf.key, sec.key)}>{sec.label}</button>
			{/each}
		{/if}
	</div>
{/if}

<main class="main">
	<slot />
</main>
