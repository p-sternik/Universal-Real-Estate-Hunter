const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('src/services/templates/assets/js/dashboard.js', 'utf8');
const elements = new Map();
function element(id, value = '') {
    const classes = new Set();
    const result = {
        id, value, type: 'number', disabled: false, checked: false,
        validity: { badInput: false }, style: {}, dataset: {},
        classList: { add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x) },
        setAttribute() {}, removeAttribute() {}, focus() {},
        insertAdjacentElement(_where, error) { elements.set(error.id, error); },
    };
    elements.set(id, result);
    return result;
}
const root = element('configModal');
const hiddenTab = element('configTabScheduler');
hiddenTab.style.display = 'none';
hiddenTab.parentElement = root;
const context = vm.createContext({
    console, structuredClone,
    document: {
        getElementById: id => elements.get(id),
        querySelectorAll: () => [],
        createElement: () => ({ id: '', className: '', textContent: '' }),
        body: { classList: { remove() {} } },
    },
    allProfiles: [], commuteDestinations: [], currentProfileId: null,
    switchConfigTab() {}, showToast() {}, restoreModalFocus() {}, renderProfileTabs() {},
    showConfirmDialog: async () => true,
});
vm.runInContext(source.slice(source.indexOf('        let settingsBaseline'), source.indexOf('        function switchConfigTab')), context);
vm.runInContext(source.slice(source.indexOf('        function validateConfigNumber'), source.indexOf('        function configTabForField')), context);
vm.runInContext(source.slice(source.indexOf('        function saveCurrentFormIntoMemory'), source.indexOf('        function openConfigModal')), context);
vm.runInContext(source.slice(source.indexOf('        async function closeConfigModal'), source.indexOf('        // ========================', source.indexOf('        async function closeConfigModal'))), context);
// A hidden settings tab is still validated; fractional integers and invalid hours are rejected.
const pages = element('pages', '2.5');
pages.parentElement = hiddenTab;
assert.equal(vm.runInContext("validateConfigNumber('pages', { integer: true, min: 1, max: 50 })", context), false);
pages.value = '2';
assert.equal(vm.runInContext("validateConfigNumber('pages', { integer: true, min: 1, max: 50 })", context), true);
const time = element('time', '24:61');
time.parentElement = hiddenTab;
assert.equal(vm.runInContext("validateConfigNumber('time', { pattern: /^(?:[01]\\d|2[0-3]):[0-5]\\d$/ })", context), false);
const number = element('number', '0');
assert.equal(vm.runInContext("settingsNumber('number', 15)", context), 0);
number.value = '';
assert.equal(vm.runInContext("settingsNumber('number')", context), null);
// Saving into a local draft retains radius 0 and an unlimited budget.
for (const id of [...source.matchAll(/getElementById\('(cfg[^']+)'\)/g)].map(match => match[1])) {
    if (!elements.has(id)) element(id);
}
elements.get('cfgProfileCategory').value = 'mieszkanie';
elements.get('cfgProfileName').value = 'Mieszkania';
elements.get('cfgCity').value = 'Kraków';
elements.get('cfgRadius').value = '0';
elements.get('cfgMaxPrice').value = '';
context.activeConfig = { profiles: [{ id: 'test', name: 'Mieszkania', category: 'mieszkanie', city: 'Kraków', max_price: 900000 }], commute_destinations: [] };
context.allProfiles = structuredClone(context.activeConfig.profiles);
context.currentProfileId = 'test';
vm.runInContext('saveCurrentFormIntoMemory()', context);
assert.equal(context.allProfiles[0].distance_radius, 0);
assert.equal(context.allProfiles[0].max_price, null);
assert.equal(context.activeConfig.profiles[0].max_price, 900000);
assert.equal(context.allProfiles[0].min_area_plot, null);
// Discard restores the canonical profiles instead of leaking draft edits.
(async () => {
    await vm.runInContext('closeConfigModal(null, true)', context);
    assert.equal(context.allProfiles[0].max_price, 900000);
    console.log('Settings behaviour checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
