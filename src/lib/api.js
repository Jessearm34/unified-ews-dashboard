/**
 * API client — fetches data from the FastAPI backend.
 * All endpoints return JSON.
 */

const BASE = '';  // Same origin (SvelteKit proxies /api to backend)

async function request(path, options = {}) {
	const res = await fetch(`${BASE}${path}`, {
		credentials: 'include',
		headers: { 'Accept': 'application/json', ...options.headers },
		...options
	});
	if (res.status === 303 || res.status === 302) {
		// Redirect to login — let the page handle it
		return { redirect: res.headers.get('location') || '/login' };
	}
	if (!res.ok) {
		const text = await res.text();
		throw new Error(`${res.status}: ${text.slice(0, 200)}`);
	}
	return res.json();
}

export function fetchOverview(range = 'ytd', compare = false) {
	const params = new URLSearchParams({ range });
	if (compare) params.set('compare', 'true');
	return request(`/_api/overview?${params}`);
}

export function fetchQB(section, opts = {}) {
	const params = new URLSearchParams();
	if (opts.basis) params.set('basis', opts.basis);
	if (opts.range) params.set('range', opts.range);
	if (opts.metric) params.set('metric', opts.metric);
	if (opts.compare) params.set('compare', 'true');
	const qs = params.toString();
	return request(`/_api/qb/${section}${qs ? '?' + qs : ''}`);
}

export function fetchSD(section, compare = false) {
	const params = new URLSearchParams();
	if (compare) params.set('compare', 'true');
	const qs = params.toString();
	return request(`/_api/sd/${section}${qs ? '?' + qs : ''}`);
}

export function fetchGT(section, range = 'all') {
	return request(`/_api/gt/${section}?range=${range}`);
}

export function fetchIN(section = 'workers') {
	return request(`/_api/insperity/${section}`);
}

export function login(email, password, next = '/') {
	return fetch('/login', {
		method: 'POST',
		headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
		body: new URLSearchParams({ email, password, next }),
		redirect: 'manual'
	});
}

export function logout() {
	return fetch('/logout', { redirect: 'manual' });
}