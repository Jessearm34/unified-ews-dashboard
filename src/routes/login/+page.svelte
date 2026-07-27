<script>
	import { goto } from '$app/navigation';

	let email = $state('');
	let password = $state('');
	let errorMsg = $state('');
	let loading = $state(false);

	async function handleSubmit(e) {
		e.preventDefault();
		loading = true;
		errorMsg = '';

		try {
			const res = await fetch('/login', {
				method: 'POST',
				headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
				body: new URLSearchParams({ email, password, next: '/' }),
				redirect: 'manual'
			});
			if (res.status === 303 || res.status === 302) {
				const loc = res.headers.get('location') || '/';
				goto(loc);
			} else {
				const text = await res.text();
				errorMsg = text.includes('Invalid') ? 'Invalid email or password.' : 'Login failed.';
			}
		} catch (e) {
			errorMsg = 'Network error.';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>Login — EWS Unified Dashboard</title>
</svelte:head>

<div class="login-page">
	<div class="login-card">
		<h2>EWS Unified Dashboard</h2>
		<p style="color: var(--muted); margin: 0 0 20px;">Sign in</p>
		{#if errorMsg}
			<div style="background:#fef2f2;padding:10px 14px;border-radius:8px;border:1px solid #fecaca;margin-bottom:12px;">
				<p style="color: var(--bad); font-size: 13px; margin: 0;">{errorMsg}</p>
			</div>
		{/if}
		<form onsubmit={handleSubmit}>
			<input
				type="email"
				name="email"
				placeholder="you@company.com"
				required
				bind:value={email}
				style="margin-bottom:10px;"
			/>
			<input
				type="password"
				name="password"
				placeholder="Password"
				required
				bind:value={password}
				style="margin-bottom:14px;"
			/>
			<button type="submit" disabled={loading}>
				{loading ? 'Signing in...' : 'Sign in'}
			</button>
		</form>
	</div>
</div>