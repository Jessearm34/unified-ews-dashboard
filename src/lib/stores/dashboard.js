import { writable, derived } from 'svelte/store';

/** Current platform: 'overview' | 'qb' | 'sd' | 'gt' */
export const platform = writable('overview');
/** Current section within platform */
export const section = writable('overview');
/** Last-loaded data for the current view */
export const viewData = writable(null);
/** Loading state */
export const loading = writable(false);
/** Error state */
export const error = writable(null);
/** Last refresh timestamp */
export const lastRefresh = writable(null);

/** Sidebar navigation items */
export const platforms = [
	{
		key: 'qb',
		label: 'QuickBooks',
		icon: '📊',
		sections: [
			{ key: 'overview', label: 'Overview', icon: '▦' },
			{ key: 'sales', label: 'Sales', icon: '📈' },
			{ key: 'finance', label: 'Finance', icon: '💲' },
			{ key: 'profitability', label: 'Profitability', icon: '💹' },
			{ key: 'customers', label: 'Customers', icon: '👥' },
			{ key: 'accounts', label: 'Accounts', icon: '🏦' }
		]
	},
	{
		key: 'sd',
		label: 'SiteDocs',
		icon: '🛡️',
		sections: [
			{ key: 'hse', label: 'HSE Overview', icon: '🛡️' },
			{ key: 'forms', label: 'Forms & JSAs', icon: '📋' },
			{ key: 'compliance', label: 'Compliance', icon: '✅' },
			{ key: 'workers', label: 'Workers', icon: '👷' }
		]
	},
	{
		key: 'gt',
		label: 'GeoTab',
		icon: '🚛',
		sections: [
			{ key: 'fleet', label: 'Fleet Overview', icon: '📊' },
			{ key: 'maintenance', label: 'Maintenance', icon: '🔧' }
		]
	},

	// ── Insperity  (disabled — uncomment when ENABLED = True in data pipeline) ───
	// {
	// 	key: 'in',
	// 	label: 'Insperity',
	// 	icon: '👤',
	// 	sections: [
	// 		{ key: 'workers', label: 'Workers', icon: '👥' },
	// 		{ key: 'certs', label: 'Certifications', icon: '📜' },
	// 		{ key: 'training', label: 'Training', icon: '📚' },
	// 	]
	// },

	// ── Equipt  (disabled — uncomment when ENABLED = True in data pipeline) ─────
	// {
	// 	key: 'eq',
	// 	label: 'Equipt',
	// 	icon: '🔩',
	// 	sections: [
	// 		{ key: 'equipment', label: 'Equipment', icon: '🏗️' },
	// 		{ key: 'maintenance', label: 'Maintenance', icon: '🔧' },
	// 		{ key: 'inspections', label: 'Inspections', icon: '🔍' },
	// 	]
	// },
];

export const deltaUpGood = platform => ({
	qb: { revenue: true, net_income: true, cash: true, outstanding: false, overdue: false, dso: false },
	sd: { compliance: true, overdue: false, participation: true, bbso_ratio: true, close_time: false },
	gt: { idle_cost: false, violations: false, safety_score: true },
}[platform] || {});

export function ragColor(status) {
	if (!status) return '#64748b';
	return { green: '#16a34a', amber: '#ea580c', red: '#dc2626' }[status] || '#64748b';
}

export function formatValue(value, unit = '') {
	if (value == null) return '—';
	if (typeof value === 'number') {
		if (unit === '$') {
			if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
			if (Math.abs(value) >= 1000) return `$${(value / 1000).toFixed(0)}K`;
			return `$${value.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
		}
		if (unit === '%') return `${value.toFixed(1)}%`;
		if (value === Math.floor(value)) return value.toLocaleString();
		return value.toLocaleString('en-US', { maximumFractionDigits: 1 });
	}
	return String(value);
}
