<script>
	import { platform as activePlatform, section as activeSection, platforms } from '$lib/stores/dashboard.js';
	import { goto } from '$app/navigation';

	let openPlatform = $state(null);
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

	function togglePlatform(key) {
		openPlatform = openPlatform === key ? null : key;
	}
</script>

<aside class="sidebar">
	<div>
		<div class="brand">
			<div class="name">EWS<span>Dashboard</span></div>
		</div>
		<nav class="nav">
			<a
				class="nav-link"
				class:active={currentPlatform === 'overview'}
				onclick={() => navigateTo(null, null)}
				role="button"
				tabindex="0"
			>Overview</a>

			{#each platforms as pf (pf.key)}
				<details class="nav-group" open={openPlatform === pf.key}>
					<summary onclick={() => togglePlatform(pf.key)}>
						{pf.label}
					</summary>
					<div class="sub">
						{#each pf.sections as sec (sec.key)}
							<a
								class:active={currentPlatform === pf.key && currentSection === sec.key}
								onclick={() => navigateTo(pf.key, sec.key)}
								role="button"
								tabindex="0"
							>{sec.label}</a>
						{/each}
					</div>
				</details>
			{/each}
		</nav>
	</div>
	<div class="sidebar-foot">EWS</div>
</aside>
