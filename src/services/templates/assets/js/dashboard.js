        let allListings = [];
        let currentFilter = 'ALL';
        let currentViewMode = 'split';
        let map = null;
        let markersGroup = null;
        let markersMap = {};
        let coordCounts = {};
        let activeConfig = null;
        let fetchEtag = null;
        let lastServerSigs = {};
        let lastFetchAt = 0;
        let searchDebounceTimer = null;
        let gridRenderToken = 0;

        function showToast(msg) {
            const t = document.getElementById('toast');
            if (!t) return;
            t.innerText = msg;
            t.style.display = 'block';
            setTimeout(() => { t.style.display = 'none'; }, 3200);
        }

        // ========================
        // Map (Leaflet + OpenStreetMap dark tiles)
        // ========================
        function initLeafletMap(centerCoords = [50.0375, 22.0047]) {
            if (map) {
                map.setView(centerCoords, 12);
                return;
            }

            map = L.map('map', {
                center: centerCoords,
                zoom: 12,
                zoomControl: true,
                scrollWheelZoom: true,
            });

            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
                maxZoom: 19
            }).addTo(map);

            markersGroup = L.featureGroup().addTo(map);
        }

        function syncTabletToggle() {
            const tglList = document.getElementById('tglList');
            const tglMap = document.getElementById('tglMap');
            if (!tglList || !tglMap) return;
            const mapShown = document.body.classList.contains('tablet-pane-map');
            tglList.classList.toggle('active', !mapShown);
            tglMap.classList.toggle('active', mapShown);
        }

        function switchViewMode(mode) {
            currentViewMode = mode;
            document.body.classList.remove('mode-grid', 'mode-split', 'mode-map');
            document.body.classList.add('mode-' + mode);
            document.body.classList.remove('mobile-map-open');
            document.body.classList.add('tablet-pane-list');
            document.body.classList.remove('tablet-pane-map');

            document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
            if (mode === 'grid') document.getElementById('btnViewGrid')?.classList.add('active');
            if (mode === 'split') document.getElementById('btnViewSplit')?.classList.add('active');
            if (mode === 'map') document.getElementById('btnViewMap')?.classList.add('active');

            syncTabletToggle();
            syncMapFab();

            setTimeout(() => {
                if (map) map.invalidateSize();
            }, 250);
        }

        function tabletShow(pane) {
            document.body.classList.toggle('tablet-pane-map', pane === 'map');
            document.body.classList.toggle('tablet-pane-list', pane === 'list');
            syncTabletToggle();
            setTimeout(() => {
                if (map) map.invalidateSize();
            }, 150);
        }

        function toggleMobileMap() {
            document.body.classList.toggle('mobile-map-open');
            syncMapFab();
            setTimeout(() => {
                if (map) map.invalidateSize();
            }, 250);
        }

        function syncMapFab() {
            const open = document.body.classList.contains('mobile-map-open');
            const iconMap = document.getElementById('mapFabIconMap');
            const iconClose = document.getElementById('mapFabIconClose');
            if (iconMap) iconMap.style.display = open ? 'none' : '';
            if (iconClose) iconClose.style.display = open ? '' : 'none';
        }

        // ========================
        // Profiles
        // ========================
        let allProfiles = [];
        let currentProfileId = null;
        let selectedProfileId = null;
        let scrapersConfig = null;

        const CITY_CENTROIDS_JS = {
            "rzeszow": [50.0375, 22.0047],
            "krakow": [50.0647, 19.9450],
            "warszawa": [52.2297, 21.0122],
            "wroclaw": [51.1079, 17.0385],
            "lublin": [51.2465, 22.5684],
            "poznan": [52.4064, 16.9252],
            "gdansk": [54.3520, 18.6466],
            "gdynia": [54.5189, 18.5305],
            "sopot": [54.4418, 18.5600],
            "katowice": [50.2649, 19.0238],
            "lodz": [51.7592, 19.4560],
            "szczecin": [53.4285, 14.5528],
            "bialystok": [53.1325, 23.1688],
            "kielce": [50.8661, 20.6286],
            "bydgoszcz": [53.1235, 18.0084],
            "torun": [53.0138, 18.5984],
            "radom": [51.4027, 21.1471],
            "czestochowa": [50.8118, 19.1203],
            "sosnowiec": [50.2863, 19.1041],
            "gliwice": [50.2945, 18.6714],
            "zabrze": [50.3249, 18.7857],
            "olsztyn": [53.7784, 20.4801],
            "bielskobiala": [49.8224, 19.0444],
            "zielonagora": [51.9356, 15.5062],
            "siedlce": [52.1677, 22.2901],
            "tarnow": [50.0121, 20.9858],
            "krosno": [49.6887, 21.7706],
            "przemysl": [49.7839, 22.7678],
            "mielec": [50.2872, 21.4239],
            "lancut": [50.0690, 22.2310]
        };

        function getCityCenter(cityName) {
            if (!cityName) return [50.0375, 22.0047];
            const clean = cityName.toLowerCase()
                .replace(/ą/g,'a').replace(/ć/g,'c').replace(/ę/g,'e').replace(/ł/g,'l').replace(/ń/g,'n')
                .replace(/ó/g,'o').replace(/ś/g,'s').replace(/ź/g,'z').replace(/ż/g,'z')
                .replace(/[^a-z0-9]+/g, '');
            return CITY_CENTROIDS_JS[clean] || [50.0375, 22.0047];
        }

        function toggleProfileMenu(event) {
            if (event) event.stopPropagation();
            const menu = document.getElementById('profileTabsContainer');
            if (menu) menu.classList.toggle('open');
        }

        function closeProfileMenu() {
            const menu = document.getElementById('profileTabsContainer');
            if (menu) menu.classList.remove('open');
        }

        function categoryIconSvg(cat, size = 14) {
            const stroke = 'stroke="currentColor" fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"';
            if (cat === 'mieszkanie') {
                return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" ${stroke}><rect x="4" y="2" width="16" height="20" rx="1"></rect><path d="M9 22v-4h6v4"></path><path d="M8 6h.01"></path><path d="M16 6h.01"></path><path d="M12 6h.01"></path><path d="M12 10h.01"></path><path d="M12 14h.01"></path><path d="M16 10h.01"></path><path d="M16 14h.01"></path><path d="M8 10h.01"></path><path d="M8 14h.01"></path></svg>`;
            }
            if (cat === 'dzialka') {
                return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" ${stroke}><path d="M2 22 22 2"></path><path d="M11 22h7a4 4 0 0 0 4-4v-7"></path><path d="M2 13a9 9 0 0 0 18 0"></path></svg>`;
            }
            return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" ${stroke}><path d="M3 21h18"></path><path d="M5 21V7l8-4v18"></path><path d="M19 21V11l-6-4"></path><path d="M9 9v.01"></path><path d="M9 12v.01"></path><path d="M9 15v.01"></path><path d="M9 18v.01"></path></svg>`;
        }

        function switchActiveProfile(profileId) {
            selectedProfileId = profileId;
            try {
                localStorage.setItem('hunter_selected_profile_id', profileId);
            } catch(e) {}

            const prof = allProfiles.find(p => p.id === profileId) || allProfiles[0];
            if (prof) {
                const labelEl = document.getElementById('profileDropLabel');
                if (labelEl) labelEl.innerText = `${prof.name} (${prof.city} +${prof.distance_radius} km)`;
                const countEl = document.getElementById('profileDropCount');
                if (countEl) countEl.innerText = getListingsForActiveProfile().length;

                if (map) {
                    const profItemsWithCoords = getListingsForActiveProfile().filter(i => i.latitude && i.longitude);
                    if (profItemsWithCoords.length === 0 && prof.city) {
                        map.setView(getCityCenter(prof.city), 12);
                    }
                }
            }

            const pSelect = document.getElementById('filterProfile');
            if (pSelect) {
                pSelect.value = profileId;
            }

            closeProfileMenu();
            renderProfileTabs();
            applyFilters();
            if (prof) {
                showToast(`Widok profilu: ${prof.name}`);
            }
        }

        function renderProfileTabs() {
            const container = document.getElementById('profileTabsContainer');
            if (!container) return;

            if (allProfiles.length === 0) {
                container.innerHTML = '<div style="color:var(--text-muted);font-size:11px;padding:8px 10px;">Brak profili</div>';
                return;
            }

            if (!selectedProfileId || !allProfiles.some(p => p.id === selectedProfileId)) {
                try {
                    const saved = localStorage.getItem('hunter_selected_profile_id');
                    if (saved && allProfiles.some(p => p.id === saved)) {
                        selectedProfileId = saved;
                    } else {
                        selectedProfileId = allProfiles[0].id;
                    }
                } catch(e) {
                    selectedProfileId = allProfiles[0].id;
                }
            }

            const items = allProfiles.map(p => {
                const isActive = p.id === selectedProfileId;

                const count = allListings.filter(item => {
                    if (item.profile_id && item.profile_id === p.id) return true;
                    if (item.profile_name && item.profile_name === p.name) return true;
                    if ((!item.profile_id || item.profile_id === 'default') && (p.id === 'default' || p.id === allProfiles[0]?.id)) return true;
                    return false;
                }).length;

                return `
                    <button type="button" class="profile-menu-item ${isActive ? 'active' : ''}" onclick="switchActiveProfile('${escapeHtml(p.id)}')" title="${escapeHtml(p.name)} (${escapeHtml(p.city)})">
                        ${categoryIconSvg(p.category || 'dom')}
                        <span class="profile-menu-item-meta">
                            <span class="profile-menu-item-name">${escapeHtml(p.name)}</span>
                            <span class="profile-menu-item-sub">${escapeHtml(p.city)} · +${p.distance_radius ?? 15} km</span>
                        </span>
                        <span class="profile-drop-count num">${count}</span>
                    </button>
                `;
            }).join('');

            const footer = `
                <div class="profile-menu-footer">
                    <button type="button" class="profile-menu-item" onclick="openConfigModal(); switchConfigTab('profiles');">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path>
                            <circle cx="12" cy="12" r="3"></circle>
                        </svg>
                        Zarządzaj profilami
                    </button>
                </div>
            `;

            container.innerHTML = items + footer;
        }

        function getListingsForActiveProfile() {
            if (!selectedProfileId) {
                if (allProfiles.length > 0) {
                    selectedProfileId = allProfiles[0].id;
                } else {
                    return allListings;
                }
            }

            const prof = allProfiles.find(p => p.id === selectedProfileId);
            const profName = prof ? prof.name : null;

            return allListings.filter(item => {
                if (item.profile_id && item.profile_id === selectedProfileId) return true;
                if (profName && item.profile_name === profName) return true;
                if ((!item.profile_id || item.profile_id === 'default') && (selectedProfileId === 'default' || selectedProfileId === allProfiles[0]?.id)) {
                    return true;
                }
                return false;
            });
        }

        // ========================
        // Configuration modal
        // ========================
        function switchConfigTab(tab) {
            const btnP = document.getElementById('tabBtnProfiles');
            const btnS = document.getElementById('tabBtnScrapers');
            const btnSch = document.getElementById('tabBtnScheduler');
            const btnAi = document.getElementById('tabBtnAi');
            const tabP = document.getElementById('configTabProfiles');
            const tabS = document.getElementById('configTabScrapers');
            const tabSch = document.getElementById('configTabScheduler');
            const tabAi = document.getElementById('configTabAi');
            if (btnP) btnP.classList.toggle('active', tab === 'profiles');
            if (btnS) btnS.classList.toggle('active', tab === 'scrapers');
            if (btnSch) btnSch.classList.toggle('active', tab === 'scheduler');
            if (btnAi) btnAi.classList.toggle('active', tab === 'ai');
            if (tabP) tabP.style.display = (tab === 'profiles') ? 'block' : 'none';
            if (tabS) tabS.style.display = (tab === 'scrapers') ? 'block' : 'none';
            if (tabSch) tabSch.style.display = (tab === 'scheduler') ? 'block' : 'none';
            if (tabAi) tabAi.style.display = (tab === 'ai') ? 'block' : 'none';
        }

        function toggleNightModeInputs(enabled) {
            const row = document.getElementById('nightSettingsRow');
            const interval = document.getElementById('nightIntervalField');
            if (row) {
                row.style.opacity = enabled ? '1' : '0.4';
                row.style.pointerEvents = enabled ? 'auto' : 'none';
            }
            if (interval) {
                interval.style.opacity = enabled ? '1' : '0.4';
                interval.style.pointerEvents = enabled ? 'auto' : 'none';
            }
        }

        function onCategorySelectChange(cat) {
            const bDom = document.getElementById('catBoxDom');
            const bApt = document.getElementById('catBoxMieszkanie');
            const bPlot = document.getElementById('catBoxDzialka');
            if (bDom) bDom.style.display = (cat === 'dom') ? 'block' : 'none';
            if (bApt) bApt.style.display = (cat === 'mieszkanie') ? 'block' : 'none';
            if (bPlot) bPlot.style.display = (cat === 'dzialka') ? 'block' : 'none';
        }

        async function fetchConfig() {
            try {
                activeConfig = await Transport.fetchConfig();
                allProfiles = activeConfig.profiles || [];
                scrapersConfig = activeConfig.scrapers || {
                    otodom: { enabled: true, max_pages: 5 },
                    olx: { enabled: true, max_pages: 5 },
                    nieruchomosci_online: { enabled: true, max_pages: 5 },
                    morizon: { enabled: true, max_pages: 5 },
                    request_delay: 1.0
                };
                if (allProfiles.length === 0) {
                    allProfiles = [{
                        id: "default",
                        name: "Domy Rzeszów",
                        category: "dom",
                        enabled: true,
                        city: activeConfig.city || "Rzeszów",
                        distance_radius: activeConfig.distance_radius || 15,
                        market_type: activeConfig.market_type || "all",
                        owner_type: "all",
                        min_price: activeConfig.min_price || 0,
                        max_price: activeConfig.max_price || 1300000,
                        min_area_home: activeConfig.min_area_home || 90,
                        max_area_home: activeConfig.max_area_home || 145,
                        min_area_plot: activeConfig.min_area_plot || 250,
                        blacklist_keywords: activeConfig.blacklist_keywords || []
                    }];
                }

                if (!selectedProfileId || !allProfiles.some(p => p.id === selectedProfileId)) {
                    try {
                        const saved = localStorage.getItem('hunter_selected_profile_id');
                        if (saved && allProfiles.some(p => p.id === saved)) {
                            selectedProfileId = saved;
                        } else {
                            selectedProfileId = allProfiles[0].id;
                        }
                    } catch(e) {
                        selectedProfileId = allProfiles[0].id;
                    }
                }

                const pSelect = document.getElementById('filterProfile');
                if (pSelect) {
                    pSelect.innerHTML = '<option value="ALL">Wszystkie profile</option>' +
                        allProfiles.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)} (${escapeHtml(p.city)})</option>`).join('');
                    pSelect.value = selectedProfileId;
                    pSelect.onchange = function() { switchActiveProfile(this.value); };
                }

                renderProfileTabs();

                const curProf = allProfiles.find(p => p.id === selectedProfileId) || allProfiles[0];
                const labelEl = document.getElementById('profileDropLabel');
                if (labelEl && curProf) {
                    labelEl.innerText = `${curProf.name} (${curProf.city} +${curProf.distance_radius} km)`;
                }
            } catch (err) {
                console.error("Failed to load config:", err);
            }
        }

        function refreshProfileSelect() {
            const sel = document.getElementById('cfgProfileSelect');
            if (!sel) return;
            sel.innerHTML = allProfiles.map(p => {
                const stateDot = p.enabled ? '●' : '○';
                return `<option value="${p.id}">${stateDot} ${escapeHtml(p.name)} (${p.city})</option>`;
            }).join('');
            if (currentProfileId) sel.value = currentProfileId;
        }

        function loadProfileIntoForm(profId) {
            const p = allProfiles.find(x => x.id === profId) || allProfiles[0];
            if (!p) return;
            currentProfileId = p.id;

            document.getElementById('cfgProfileName').value = p.name || '';
            document.getElementById('cfgProfileCategory').value = p.category || 'dom';
            document.getElementById('cfgProfileEnabled').checked = p.enabled !== false;
            document.getElementById('cfgCity').value = p.city || 'Rzeszów';
            document.getElementById('cfgRadius').value = p.distance_radius ?? 15;
            document.getElementById('cfgMarket').value = p.market_type || 'all';
            document.getElementById('cfgOwnerType').value = p.owner_type || 'all';
            document.getElementById('cfgMinPrice').value = p.min_price || 0;
            document.getElementById('cfgMaxPrice').value = p.max_price || 1300000;
            document.getElementById('cfgMinPriceM2').value = p.min_price_per_m2 || '';
            document.getElementById('cfgMaxPriceM2').value = p.max_price_per_m2 || '';
            document.getElementById('cfgMinYearBuilt').value = p.min_year_built || '';
            document.getElementById('cfgMaxYearBuilt').value = p.max_year_built || '';
            document.getElementById('cfgBlacklist').value = (p.blacklist_keywords || []).join(', ');
            document.getElementById('cfgDiscordWebhook').value = p.discord_webhook_url || '';
            document.getElementById('cfgOtodomPath').value = p.otodom_path || '';

            const finishAllowed = p.allowed_finish_conditions || [];
            const finishAll = finishAllowed.includes('all');
            document.querySelectorAll('.cfg-finish').forEach(cb => { cb.checked = !finishAll && finishAllowed.includes(cb.value); });
            const buildingAllowed = p.building_types || [];
            document.querySelectorAll('.cfg-building').forEach(cb => { cb.checked = buildingAllowed.includes(cb.value); });
            const heatingAllowed = p.allowed_heating_types || [];
            const heatingAll = heatingAllowed.includes('all');
            document.querySelectorAll('.cfg-heating').forEach(cb => { cb.checked = !heatingAll && heatingAllowed.includes(cb.value); });
            document.getElementById('cfgRejectSeptic').checked = !!p.reject_septic_tank;
            document.getElementById('cfgAllowVis').checked = p.allow_visualisations !== false;

            document.getElementById('cfgMinAreaHome').value = p.min_area_home || '';
            document.getElementById('cfgMaxAreaHome').value = p.max_area_home || '';
            document.getElementById('cfgMinAreaPlot').value = p.min_area_plot || '';
            document.getElementById('cfgMaxAreaPlot').value = p.max_area_plot || '';

            document.getElementById('cfgMinAreaApt').value = p.min_area_home || '';
            document.getElementById('cfgMaxAreaApt').value = p.max_area_home || '';
            document.getElementById('cfgMinRooms').value = p.min_rooms || '';
            document.getElementById('cfgMaxRooms').value = p.max_rooms || '';
            document.getElementById('cfgMinFloor').value = (p.min_floor !== undefined && p.min_floor !== null) ? p.min_floor : '';
            document.getElementById('cfgMaxFloor').value = (p.max_floor !== undefined && p.max_floor !== null) ? p.max_floor : '';

            document.getElementById('cfgMinAreaPlotOnly').value = p.min_area_plot || '';
            document.getElementById('cfgMaxAreaPlotOnly').value = p.max_area_plot || '';

            onCategorySelectChange(p.category || 'dom');
        }

        function onProfileSelectChange(val) {
            saveCurrentFormIntoMemory();
            currentProfileId = val;
            loadProfileIntoForm(val);
        }

        function createNewProfile() {
            saveCurrentFormIntoMemory();
            const newId = "profile_" + Date.now();
            const newP = {
                id: newId,
                name: "Nowy profil " + (allProfiles.length + 1),
                category: "mieszkanie",
                enabled: true,
                city: "Kraków",
                distance_radius: 10,
                market_type: "all",
                owner_type: "all",
                min_price: 300000,
                max_price: 900000,
                min_area_home: 40,
                max_area_home: 80,
                min_rooms: 2,
                max_rooms: 4,
                blacklist_keywords: [],
                allowed_finish_conditions: ["all"],
                building_types: ["szeregowiec", "bliźniak", "wolnostojący", "inny"],
                allowed_heating_types: ["all"],
                allow_visualisations: true,
                reject_septic_tank: false
            };
            allProfiles.push(newP);
            currentProfileId = newId;
            refreshProfileSelect();
            loadProfileIntoForm(newId);
            showToast("Utworzono nowy profil");
        }

        async function deleteCurrentProfile() {
            if (allProfiles.length <= 1) {
                alert("Nie można usunąć jedynego profilu wyszukiwania.");
                return;
            }
            const profName = document.getElementById('cfgProfileName').value || currentProfileId;
            if (!confirm(`Czy na pewno chcesz usunąć profil "${profName}" oraz WSZYSTKIE powiązane z nim oferty z bazy danych?\n\nTej operacji nie można cofnąć.`)) {
                return;
            }

            const idToDelete = currentProfileId;
            try {
                const resData = await Transport.deleteProfile(idToDelete);
                const deletedListingsCount = resData.deleted_listings || 0;

                const idx = allProfiles.findIndex(p => p.id === idToDelete);
                if (idx >= 0) {
                    allProfiles.splice(idx, 1);
                }

                if (selectedProfileId === idToDelete) {
                    selectedProfileId = allProfiles[0].id;
                }
                currentProfileId = allProfiles[0].id;

                refreshProfileSelect();
                loadProfileIntoForm(currentProfileId);

                showToast(`Usunięto profil "${profName}" oraz ${deletedListingsCount} ofert z bazy danych.`);

                await fetchListings();
                renderProfileTabs();
                switchActiveProfile(currentProfileId);
            } catch (err) {
                console.error("Failed to delete profile:", err);
                showToast("Błąd podczas usuwania profilu.");
            }
        }

        function saveCurrentFormIntoMemory() {
            const p = allProfiles.find(x => x.id === currentProfileId);
            if (!p) return;
            const cat = document.getElementById('cfgProfileCategory').value;
            p.name = document.getElementById('cfgProfileName').value.trim() || p.name;
            p.category = cat;
            p.enabled = document.getElementById('cfgProfileEnabled').checked;
            p.city = document.getElementById('cfgCity').value.trim() || 'Rzeszów';
            p.distance_radius = parseInt(document.getElementById('cfgRadius').value) || 15;
            p.market_type = document.getElementById('cfgMarket').value;
            p.owner_type = document.getElementById('cfgOwnerType').value;
            p.min_price = parseFloat(document.getElementById('cfgMinPrice').value) || 0;
            p.max_price = parseFloat(document.getElementById('cfgMaxPrice').value) || 1300000;
            p.min_price_per_m2 = parseFloat(document.getElementById('cfgMinPriceM2').value) || null;
            p.max_price_per_m2 = parseFloat(document.getElementById('cfgMaxPriceM2').value) || null;
            p.min_year_built = parseInt(document.getElementById('cfgMinYearBuilt').value) || null;
            p.max_year_built = parseInt(document.getElementById('cfgMaxYearBuilt').value) || null;
            const blRaw = document.getElementById('cfgBlacklist').value;
            p.blacklist_keywords = blRaw.split(',').map(s => s.trim().toLowerCase()).filter(s => s.length > 0);
            p.discord_webhook_url = document.getElementById('cfgDiscordWebhook').value.trim() || null;
            p.otodom_path = document.getElementById('cfgOtodomPath')?.value.trim() || null;

            const finishSel = Array.from(document.querySelectorAll('.cfg-finish:checked')).map(cb => cb.value);
            p.allowed_finish_conditions = finishSel.length > 0 ? finishSel : ["all"];
            p.building_types = Array.from(document.querySelectorAll('.cfg-building:checked')).map(cb => cb.value);
            const heatingSel = Array.from(document.querySelectorAll('.cfg-heating:checked')).map(cb => cb.value);
            p.allowed_heating_types = heatingSel.length > 0 ? heatingSel : ["all"];
            p.reject_septic_tank = document.getElementById('cfgRejectSeptic').checked;
            p.allow_visualisations = document.getElementById('cfgAllowVis').checked;

            if (cat === 'dom') {
                p.min_area_home = parseFloat(document.getElementById('cfgMinAreaHome').value) || 0;
                p.max_area_home = parseFloat(document.getElementById('cfgMaxAreaHome').value) || null;
                p.min_area_plot = parseFloat(document.getElementById('cfgMinAreaPlot').value) || 0;
                p.max_area_plot = parseFloat(document.getElementById('cfgMaxAreaPlot').value) || null;
            } else if (cat === 'mieszkanie') {
                p.min_area_home = parseFloat(document.getElementById('cfgMinAreaApt').value) || 0;
                p.max_area_home = parseFloat(document.getElementById('cfgMaxAreaApt').value) || null;
                p.min_rooms = parseInt(document.getElementById('cfgMinRooms').value) || null;
                p.max_rooms = parseInt(document.getElementById('cfgMaxRooms').value) || null;
                const minF = document.getElementById('cfgMinFloor').value;
                p.min_floor = minF !== '' ? parseInt(minF) : null;
                const maxF = document.getElementById('cfgMaxFloor').value;
                p.max_floor = maxF !== '' ? parseInt(maxF) : null;
            } else if (cat === 'dzialka') {
                p.min_area_plot = parseFloat(document.getElementById('cfgMinAreaPlotOnly').value) || 0;
                p.max_area_plot = parseFloat(document.getElementById('cfgMaxAreaPlotOnly').value) || null;
            }
        }

        function openConfigModal() {
            if (!activeConfig) return;
            switchConfigTab('profiles');

            const sc = scrapersConfig || {};
            document.getElementById('cfgScraperOtodom').checked = sc.otodom ? sc.otodom.enabled !== false : true;
            document.getElementById('cfgPagesOtodom').value = sc.otodom?.max_pages || 5;
            document.getElementById('cfgScraperOlx').checked = sc.olx ? sc.olx.enabled !== false : true;
            document.getElementById('cfgPagesOlx').value = sc.olx?.max_pages || 5;
            document.getElementById('cfgScraperNieruchomosci').checked = sc.nieruchomosci_online ? sc.nieruchomosci_online.enabled !== false : true;
            document.getElementById('cfgPagesNieruchomosci').value = sc.nieruchomosci_online?.max_pages || 5;
            document.getElementById('cfgScraperMorizon').checked = sc.morizon ? sc.morizon.enabled !== false : true;
            document.getElementById('cfgPagesMorizon').value = sc.morizon?.max_pages || 5;
            document.getElementById('cfgRequestDelay').value = sc.request_delay ?? 1.0;

            const sched = activeConfig.scheduler || {};
            if (document.getElementById('cfgIntervalMinutes')) {
                document.getElementById('cfgIntervalMinutes').value = sched.interval_minutes || 20;
            }
            if (document.getElementById('cfgNightMode')) {
                document.getElementById('cfgNightMode').checked = sched.night_mode !== false;
                toggleNightModeInputs(sched.night_mode !== false);
            }
            if (document.getElementById('cfgQuietStart')) {
                document.getElementById('cfgQuietStart').value = sched.quiet_hours_start || '22:00';
            }
            if (document.getElementById('cfgQuietEnd')) {
                document.getElementById('cfgQuietEnd').value = sched.quiet_hours_end || '07:00';
            }
            if (document.getElementById('cfgNightIntervalMinutes')) {
                document.getElementById('cfgNightIntervalMinutes').value = sched.night_interval_minutes || 60;
            }

            if (document.getElementById('cfgLlmAnalysis')) {
                document.getElementById('cfgLlmAnalysis').checked = !!activeConfig.llm_analysis_enabled;
            }

            if (!currentProfileId && allProfiles.length > 0) {
                currentProfileId = allProfiles[0].id;
            }
            refreshProfileSelect();
            loadProfileIntoForm(currentProfileId);

            document.getElementById('configModal').classList.add('open');
            closeProfileMenu();
        }

        function closeConfigModal(e) {
            if (!e || e.target.id === 'configModal' || e === null) {
                document.getElementById('configModal').classList.remove('open');
            }
        }

        function setCfgCity(city) {
            document.getElementById('cfgCity').value = city;
        }

        async function saveConfiguration(triggerScrapingImmediately = false) {
            saveCurrentFormIntoMemory();

            const scrapersPayload = {
                otodom: {
                    enabled: document.getElementById('cfgScraperOtodom').checked,
                    max_pages: parseInt(document.getElementById('cfgPagesOtodom').value) || 5
                },
                olx: {
                    enabled: document.getElementById('cfgScraperOlx').checked,
                    max_pages: parseInt(document.getElementById('cfgPagesOlx').value) || 5
                },
                nieruchomosci_online: {
                    enabled: document.getElementById('cfgScraperNieruchomosci').checked,
                    max_pages: parseInt(document.getElementById('cfgPagesNieruchomosci').value) || 5
                },
                morizon: {
                    enabled: document.getElementById('cfgScraperMorizon').checked,
                    max_pages: parseInt(document.getElementById('cfgPagesMorizon').value) || 5
                },
                request_delay: parseFloat(document.getElementById('cfgRequestDelay').value) || 1.0
            };

            const schedulerPayload = {
                interval_minutes: parseInt(document.getElementById('cfgIntervalMinutes')?.value) || 20,
                night_mode: document.getElementById('cfgNightMode')?.checked ?? true,
                quiet_hours_start: document.getElementById('cfgQuietStart')?.value || '22:00',
                quiet_hours_end: document.getElementById('cfgQuietEnd')?.value || '07:00',
                night_interval_minutes: parseInt(document.getElementById('cfgNightIntervalMinutes')?.value) || 60
            };

            const payload = {
                profiles: allProfiles,
                scrapers: scrapersPayload,
                scheduler: schedulerPayload,
                llm_analysis_enabled: document.getElementById('cfgLlmAnalysis')?.checked ?? false
            };

            try {
                activeConfig = await Transport.saveConfig(payload);
                allProfiles = activeConfig.profiles || allProfiles;
                scrapersConfig = activeConfig.scrapers || scrapersPayload;
                document.getElementById('configModal').classList.remove('open');
                showToast("Zapisano konfigurację");

                await fetchConfig();

                if (triggerScrapingImmediately) {
                    triggerScrape();
                } else {
                    await fetchListings();
                }
            } catch (err) {
                console.error("Failed to save config:", err);
                showToast("Błąd zapisu konfiguracji.");
            }
        }

        async function resetDatabaseData() {
            const scope = currentProfileId || null;
            const scopeLabel = scope ? `profilu "${scope}"` : 'CAŁEJ bazy danych';
            const typed = prompt(
                `UWAGA: Usuniesz WSZYSTKIE oferty z ${scopeLabel}\n(wraz z historią cen, notatkami i statusami CRM).\n\nAby potwierdzić, wpisz: RESET`,
                ''
            );
            if (typed !== 'RESET') {
                showToast('Anulowano — nie wpisano RESET.');
                return;
            }
            try {
                const out = await Transport.resetData({ confirm: true, profile: scope });
                showToast(`Usunięto ${out.deleted_listings} ofert (zakres: ${out.scope}).`);
                await fetchListings();
            } catch (e) {
                console.error('Reset failed:', e);
                showToast('Błąd resetu bazy danych.');
            }
        }

        // ========================
        // Listings fetching & filtering
        // ========================
        async function fetchListings() {
            lastFetchAt = Date.now();
            try {
                const out = await Transport.fetchListings(fetchEtag);
                if (out.status === 304) return;

                const newEtag = out.etag;
                const data = out.data;

                const newSigs = {};
                data.forEach(i => { newSigs[i.id] = JSON.stringify(i); });

                const firstLoad = allListings.length === 0 && fetchEtag === null;
                allListings = data;

                const changed = new Set();
                const removed = new Set();
                if (!firstLoad) {
                    for (const id of Object.keys(lastServerSigs)) {
                        if (!(id in newSigs)) removed.add(+id);
                        else if (lastServerSigs[id] !== newSigs[id]) changed.add(+id);
                    }
                    for (const id of Object.keys(newSigs)) {
                        if (!(id in lastServerSigs)) changed.add(+id);
                    }
                }
                lastServerSigs = newSigs;
                fetchEtag = newEtag;

                renderProfileTabs();
                const baseListings = getListingsForActiveProfile();
                updateStats(baseListings);

                if (firstLoad) {
                    applyFilters();
                    return;
                }
                if (changed.size === 0 && removed.size === 0) return;
                applyFiltersIncremental(changed, removed);
            } catch (err) {
                console.error("Failed to load listings:", err);
                showToast("Błąd ładowania ofert z bazy danych.");
            }
        }

        let currentPerspective = 'ALL';

        function setViewMode(perspectiveVal) {
            currentPerspective = perspectiveVal;
            const sel = document.getElementById('perspectiveSelect');
            if (sel) sel.value = perspectiveVal;
            applyFilters();
        }

        function updateStats(items) {
            const safeSet = (id, val) => {
                const el = document.getElementById(id);
                if (el) el.innerText = val;
            };

            const countAll = items.length;
            const countNew = items.filter(i => i.is_new_cycle).length;
            const countUpdated = items.filter(i => i.is_updated_cycle).length;
            const countReview = items.filter(i => i.user_status === 'NEW').length;
            const countChecked = items.filter(i => i.user_status === 'CHECKED').length;

            const pSel = document.getElementById('perspectiveSelect');
            if (pSel) {
                const setOpt = (val, txt) => {
                    const o = pSel.querySelector(`option[value="${val}"]`);
                    if (o) o.textContent = txt;
                };
                setOpt('ALL', `Cała baza (${countAll})`);
                setOpt('NEW_CYCLE', `Ostatni przebieg (${countNew})`);
                setOpt('UPDATED_CYCLE', `Korekty cen (${countUpdated})`);
                setOpt('TO_REVIEW', `Do zbadania (${countReview})`);
                setOpt('CHECKED', `Sprawdzone (${countChecked})`);
            }

            let viewItems = items;
            if (currentPerspective === 'NEW_CYCLE') {
                viewItems = items.filter(i => i.is_new_cycle);
            } else if (currentPerspective === 'UPDATED_CYCLE') {
                viewItems = items.filter(i => i.is_updated_cycle);
            } else if (currentPerspective === 'TO_REVIEW') {
                viewItems = items.filter(i => i.user_status === 'NEW');
            } else if (currentPerspective === 'CHECKED') {
                viewItems = items.filter(i => i.user_status === 'CHECKED');
            }

            const total = viewItems.length;
            const favs = viewItems.filter(i => i.user_status === 'FAVORITE').length;
            const toVisit = viewItems.filter(i => i.user_status === 'TO_VISIT').length;
            const wl = viewItems.filter(i => i.qualification_status === 'QUALIFIED_WHITELIST').length;
            const qual = viewItems.filter(i => i.is_qualified).length;
            const rev = viewItems.filter(i => i.qualification_status === 'NEEDS_REVIEW').length;
            const border = viewItems.filter(i => i.qualification_status === 'NEEDS_REVIEW_BORDERLINE').length;
            const rej = viewItems.filter(i => i.user_status === 'REJECTED' || i.qualification_status.startsWith('REJECTED')).length;
            const newCnt = viewItems.filter(i => i.is_new_cycle).length;

            safeSet('stTotal', total);
            safeSet('cntAll', total);
            safeSet('cntTotalAll', total);
            safeSet('stNew', newCnt);
            safeSet('stFavorite', favs);
            safeSet('cntFav', favs);
            safeSet('stToVisit', toVisit);
            safeSet('cntVisit', toVisit);
            safeSet('stWhitelist', wl);
            safeSet('cntWl', wl);
            safeSet('stQualified', qual);
            safeSet('cntQual', qual);
            safeSet('cntRev', rev);
            safeSet('cntBorder', border);
            safeSet('cntRej', rej);

            safeSet('vpbCountAll', countAll);
            safeSet('vpbCountNew', countNew);
            safeSet('vpbCountUpdated', countUpdated);
            safeSet('vpbCountReview', countReview);
            safeSet('vpbCountChecked', countChecked);

            const priced = viewItems.filter(i => i.price_per_m2 > 0);
            const avg = priced.length > 0 ? priced.reduce((acc, c) => acc + c.price_per_m2, 0) / priced.length : 0;
            safeSet('stAvgPrice', Math.round(avg).toLocaleString('pl-PL') + ' zł/m²');
            safeSet('stAvgCount', priced.length);

            const countEl = document.getElementById('profileDropCount');
            if (countEl) countEl.innerText = countAll;
        }

        function setFilter(filterVal, el) {
            document.querySelectorAll('.pipe-item').forEach(b => b.classList.toggle('active', b.dataset.filter === filterVal));
            currentFilter = filterVal;
            applyFilters();
        }

        function resetLiveFilters() {
            if (document.getElementById('filterCategory')) document.getElementById('filterCategory').value = 'ALL';
            if (document.getElementById('filterProfile')) document.getElementById('filterProfile').value = 'ALL';
            if (document.getElementById('filterMaxPrice')) document.getElementById('filterMaxPrice').value = '';
            if (document.getElementById('filterMinArea')) document.getElementById('filterMinArea').value = '';
            if (document.getElementById('filterMaxArea')) document.getElementById('filterMaxArea').value = '';
            if (document.getElementById('filterMinPlot')) document.getElementById('filterMinPlot').value = '';
            if (document.getElementById('filterMarket')) document.getElementById('filterMarket').value = 'ALL';
            if (document.getElementById('filterBuildingType')) document.getElementById('filterBuildingType').value = 'ALL';
            if (document.getElementById('filterFinish')) document.getElementById('filterFinish').value = 'ALL';
            if (document.getElementById('filterVis')) document.getElementById('filterVis').value = 'ALL';
            if (document.getElementById('filterSewerage')) document.getElementById('filterSewerage').value = 'ALL';
            if (document.getElementById('filterHeating')) document.getElementById('filterHeating').value = 'ALL';
            if (document.getElementById('searchInput')) document.getElementById('searchInput').value = '';
            setFilter('ALL');
        }

        function computeFilteredItems() {
            const query = (document.getElementById('searchInput')?.value || '').toLowerCase().trim();
            const sortMode = document.getElementById('sortSelect')?.value || 'score_desc';

            const categoryVal = document.getElementById('filterCategory')?.value || 'ALL';
            const maxPriceVal = parseFloat(document.getElementById('filterMaxPrice')?.value) || null;
            const minAreaVal = parseFloat(document.getElementById('filterMinArea')?.value) || null;
            const maxAreaVal = parseFloat(document.getElementById('filterMaxArea')?.value) || null;
            const minPlotVal = parseFloat(document.getElementById('filterMinPlot')?.value) || null;
            const marketVal = document.getElementById('filterMarket')?.value || 'ALL';
            const buildingTypeVal = document.getElementById('filterBuildingType')?.value || 'ALL';
            const finishVal = document.getElementById('filterFinish')?.value || 'ALL';
            const visVal = document.getElementById('filterVis')?.value || 'ALL';
            const sewerageVal = document.getElementById('filterSewerage')?.value || 'ALL';
            const heatingVal = document.getElementById('filterHeating')?.value || 'ALL';

            const baseListings = getListingsForActiveProfile();

            let filtered = baseListings.filter(item => {
                if (currentPerspective === 'NEW_CYCLE' && !item.is_new_cycle) return false;
                if (currentPerspective === 'UPDATED_CYCLE' && !item.is_updated_cycle) return false;
                if (currentPerspective === 'TO_REVIEW' && item.user_status !== 'NEW') return false;
                if (currentPerspective === 'CHECKED' && item.user_status !== 'CHECKED') return false;

                if (currentFilter === 'CRM_FAVORITE' && item.user_status !== 'FAVORITE') return false;
                if (currentFilter === 'CRM_TO_VISIT' && item.user_status !== 'TO_VISIT') return false;
                if (currentFilter === 'QUALIFIED_WHITELIST' && item.qualification_status !== 'QUALIFIED_WHITELIST') return false;
                if (currentFilter === 'QUALIFIED' && !item.is_qualified) return false;
                if (currentFilter === 'NEEDS_REVIEW' && item.qualification_status !== 'NEEDS_REVIEW') return false;
                if (currentFilter === 'NEEDS_REVIEW_BORDERLINE' && item.qualification_status !== 'NEEDS_REVIEW_BORDERLINE') return false;
                if (currentFilter === 'REJECTED' && item.user_status !== 'REJECTED' && !item.qualification_status.startsWith('REJECTED')) return false;
                if (currentFilter === 'NEW' && !item.is_new_cycle) return false;

                if (categoryVal !== 'ALL' && item.category !== categoryVal) return false;

                if (maxPriceVal && item.price > maxPriceVal) return false;
                if (minAreaVal && item.area_home < minAreaVal) return false;
                if (maxAreaVal && item.area_home > maxAreaVal) return false;
                if (minPlotVal && (item.area_plot || 0) < minPlotVal) return false;
                if (marketVal !== 'ALL' && item.market !== marketVal) return false;
                if (buildingTypeVal !== 'ALL' && item.building_type !== buildingTypeVal) return false;
                if (finishVal !== 'ALL' && item.finish_condition !== finishVal) return false;
                if (visVal === 'NO_VIS' && item.has_visualisations) return false;
                if (visVal === 'ONLY_VIS' && !item.has_visualisations) return false;
                if (sewerageVal !== 'ALL' && item.sewerage !== sewerageVal) return false;
                if (heatingVal !== 'ALL' && item.heating !== heatingVal) return false;

                if (query) {
                    const haystack = [
                        item.title, item.location_raw, item.street, item.district, item.city,
                        item.building_type, item.user_notes, item.sewerage, item.heating,
                        ...(item.pros || []), ...(item.cons || []),
                        ...(item.filter_reasons || [])
                    ].join(" ").toLowerCase();
                    if (!haystack.includes(query)) return false;
                }
                return true;
            });

            if (sortMode === 'score_desc') {
                filtered.sort((a, b) => b.qualification_score - a.qualification_score);
            } else if (sortMode === 'price_asc') {
                filtered.sort((a, b) => a.price - b.price);
            } else if (sortMode === 'price_desc') {
                filtered.sort((a, b) => b.price - a.price);
            } else if (sortMode === 'area_desc') {
                filtered.sort((a, b) => b.area_home - a.area_home);
            } else if (sortMode === 'price_m2_asc') {
                filtered.sort((a, b) => a.price_per_m2 - b.price_per_m2);
            } else if (sortMode === 'created_desc') {
                filtered.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
            }

            return filtered;
        }

        function updateFilteredCount(count) {
            const cntEl = document.getElementById('cntFiltered');
            if (cntEl) cntEl.innerText = count;
            const tglEl = document.getElementById('tglListCount');
            if (tglEl) tglEl.innerText = count;
        }

        function debouncedApplyFilters() {
            clearTimeout(searchDebounceTimer);
            searchDebounceTimer = setTimeout(applyFilters, 250);
        }

        function applyFilters() {
            const baseListings = getListingsForActiveProfile();
            updateStats(baseListings);
            const filtered = computeFilteredItems();
            updateFilteredCount(filtered.length);
            renderGrid(filtered);
            renderMapMarkers(filtered);
            renderFilterTokens();
        }

        function applyFiltersIncremental(changedSet, removedSet) {
            const baseListings = getListingsForActiveProfile();
            updateStats(baseListings);
            const filtered = computeFilteredItems();
            updateFilteredCount(filtered.length);
            renderGridIncremental(filtered, changedSet);
            updateMapMarkers(filtered, changedSet, removedSet);
            renderFilterTokens();
        }

        // ========================
        // Faceted search tokens
        // ========================
        function filterOptionText(el) {
            if (!el || !el.value) return null;
            const opt = Array.from(el.options).find(o => o.value === el.value);
            return opt ? opt.textContent.trim() : el.value;
        }

        function fmtNum(n) { return Number(n).toLocaleString('pl-PL'); }

        function renderFilterTokens() {
            const box = document.getElementById('filterTokens');
            const badge = document.getElementById('activeFilterCount');
            if (!box) return;

            const t = [];
            const add = (id, label, text) => { if (text) t.push({ id, label, text }); };
            const sel = (id, label) => {
                const el = document.getElementById(id);
                if (el && el.value && el.value !== 'ALL') add(id, label, filterOptionText(el));
            };

            sel('filterCategory', 'Kategoria');
            const maxP = parseFloat(document.getElementById('filterMaxPrice')?.value);
            if (maxP) add('filterMaxPrice', 'Cena', `≤ ${fmtNum(maxP)} zł`);
            const minA = parseFloat(document.getElementById('filterMinArea')?.value);
            const maxA = parseFloat(document.getElementById('filterMaxArea')?.value);
            if (minA || maxA) {
                const part = minA ? `≥ ${fmtNum(minA)}` : '';
                const part2 = maxA ? `≤ ${fmtNum(maxA)}` : '';
                add(minA ? 'filterMinArea' : 'filterMaxArea', 'Metraż', [part, part2].filter(Boolean).join(' ') + ' m²');
            }
            const minPlot = parseFloat(document.getElementById('filterMinPlot')?.value);
            if (minPlot) add('filterMinPlot', 'Działka', `≥ ${fmtNum(minPlot)} m²`);
            sel('filterMarket', 'Rynek');
            sel('filterBuildingType', 'Zabudowa');
            sel('filterFinish', 'Stan');
            sel('filterVis', 'Zdjęcia');
            sel('filterSewerage', 'Ścieki');
            sel('filterHeating', 'Ogrzewanie');

            const xSvg = `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>`;

            box.innerHTML = t.map(tk =>
                `<button type="button" class="filter-token" onclick="clearToken('${tk.id}')" title="Usuń filtr"><span>${tk.label}</span><b>${tk.text}</b>${xSvg}</button>`
            ).join('');

            if (badge) badge.innerText = t.length;
        }

        function clearToken(id) {
            const el = document.getElementById(id);
            if (!el) return;
            if (el.tagName === 'SELECT') {
                el.value = 'ALL';
            } else {
                el.value = '';
            }
            if (id === 'filterMinArea') {
                const maxEl = document.getElementById('filterMaxArea');
                if (maxEl) maxEl.value = '';
            }
            if (id === 'filterMaxArea') {
                const minEl = document.getElementById('filterMinArea');
                if (minEl) minEl.value = '';
            }
            applyFilters();
        }

        function toggleFiltersPopover(event) {
            if (event) event.stopPropagation();
            const pop = document.getElementById('filtersPopover');
            if (!pop) return;
            pop.classList.toggle('open');
            document.body.classList.toggle('filters-open', pop.classList.contains('open'));
        }

        function closeFiltersPopover() {
            const pop = document.getElementById('filtersPopover');
            if (pop) pop.classList.remove('open');
            document.body.classList.remove('filters-open');
        }

        // ========================
        // Map markers
        // ========================
        function addMapMarker(item) {
            let pinClass = "pin-blue";
            const cat = item.category || 'dom';
            let pinChar = cat === 'mieszkanie' ? 'M' : (cat === 'dzialka' ? 'Z' : 'D');

            if (item.user_status === 'FAVORITE') {
                pinClass = "pin-gold";
                pinChar = "★";
            } else if (item.user_status === 'TO_VISIT') {
                pinClass = "pin-purple";
                pinChar = "W";
            } else if (item.user_status === 'CHECKED') {
                pinClass = "pin-green";
                pinChar = "✓";
            } else if (item.user_status === 'REJECTED' || item.qualification_status.startsWith('REJECTED')) {
                pinClass = "pin-gray";
                pinChar = "×";
            } else if (item.qualification_status === 'QUALIFIED_WHITELIST') {
                pinClass = "pin-green";
                pinChar = "★";
            } else if (item.qualification_status === 'NEEDS_REVIEW') {
                pinClass = "pin-orange";
                pinChar = "?";
            } else if (item.qualification_status === 'NEEDS_REVIEW_BORDERLINE') {
                pinClass = "pin-orange";
                pinChar = "≈";
            }

            if (!item.is_exact_coords) {
                pinClass += " pin-approx";
            }

            const coordKey = `${item.latitude.toFixed(4)},${item.longitude.toFixed(4)}`;
            coordCounts[coordKey] = (coordCounts[coordKey] || 0) + 1;
            const offsetMultiplier = (coordCounts[coordKey] - 1);
            const jitterLat = item.latitude + (offsetMultiplier * 0.00015);
            const jitterLon = item.longitude + (offsetMultiplier * 0.0002);

            const iconHtml = `<div class="custom-pin ${pinClass}" title="${escapeHtml(item.title)}">${pinChar}</div>`;
            const icon = L.divIcon({
                html: iconHtml,
                className: 'custom-div-icon',
                iconSize: [24, 24],
                iconAnchor: [12, 12],
                popupAnchor: [0, -12]
            });

            const marker = L.marker([jitterLat, jitterLon], { icon: icon });

            const fallbackImg = "https://images.unsplash.com/photo-1580587771525-78b9dba3b914?auto=format&fit=crop&w=400&q=80";
            const imgSrc = item.main_image_url || fallbackImg;
            const plotText = item.area_plot ? `${Math.round(item.area_plot)} m²` : 'b/d';
            const precisionText = item.is_exact_coords ? 'Lokalizacja dokładna' : 'Lokalizacja przybliżona (rejon)';
            const precisionColor = item.is_exact_coords ? 'var(--slate-text)' : 'var(--amber-text)';
            const specsText = cat === 'dzialka'
                ? `Działka: ${plotText}`
                : (cat === 'mieszkanie' ? `${item.area_home.toFixed(0)} m² • ${item.rooms ? item.rooms + ' pok. • ' : ''}` : `${item.area_home.toFixed(0)} m² • Działka: ${plotText} • `);

            const popupHtml = `
                <div class="popup-card">
                    <img src="${escapeHtml(imgSrc)}" class="popup-img" onerror="this.src='${fallbackImg}'" onclick="openImgModal('${escapeHtml(imgSrc)}')">
                    <div class="popup-body">
                        <div class="popup-price num">${Math.round(item.price).toLocaleString('pl-PL')} zł</div>
                        <div class="popup-title"><a href="${escapeHtml(item.url)}" target="_blank">${escapeHtml(item.title)}</a></div>
                        <div class="popup-specs">${escapeHtml(specsText)}${escapeHtml(item.street || item.district || item.city || '')}</div>
                        <div class="popup-precision" style="color: ${precisionColor};">${precisionText}</div>
                        <div class="popup-actions">
                            <button class="btn btn-sm ${item.user_status === 'FAVORITE' ? 'active-fav' : ''}" onclick="updateStatus(${item.id}, 'FAVORITE')">★</button>
                            <button class="btn btn-sm ${item.user_status === 'TO_VISIT' ? 'active-visit' : ''}" onclick="updateStatus(${item.id}, 'TO_VISIT')">Do wizyty</button>
                            <button class="btn btn-sm" onclick="updateStatus(${item.id}, 'REJECTED')">×</button>
                            ${item.geoportal_url ? `<a href="${escapeHtml(item.geoportal_url)}" target="_blank" class="btn btn-sm" title="Geoportal">Geoportal</a>` : ''}
                        </div>
                    </div>
                </div>
            `;

            marker.bindPopup(popupHtml);
            marker.on('click', () => {
                highlightCard(item.id);
            });
            marker.on('mouseover', () => {
                const card = document.getElementById('card-' + item.id);
                if (card) card.classList.add('card-hover-highlight');
            });
            marker.on('mouseout', () => {
                const card = document.getElementById('card-' + item.id);
                if (card) card.classList.remove('card-hover-highlight');
            });

            markersGroup.addLayer(marker);
            markersMap[item.id] = marker;
            return marker;
        }

        function renderMapMarkers(items) {
            if (!map || !markersGroup) return;

            markersGroup.clearLayers();
            markersMap = {};
            coordCounts = {};

            const validCoordsItems = items.filter(i => i.latitude && i.longitude);

            validCoordsItems.forEach(addMapMarker);

            if (validCoordsItems.length > 0) {
                try {
                    map.fitBounds(markersGroup.getBounds(), { padding: [30, 30], maxZoom: 15 });
                } catch (e) {}
            }
        }

        function updateMapMarkers(items, changedSet, removedSet) {
            if (!map || !markersGroup) return;

            const wanted = new Set(items.map(i => i.id));

            for (const id of Object.keys(markersMap)) {
                if (!wanted.has(+id) || changedSet.has(+id)) {
                    markersGroup.removeLayer(markersMap[id]);
                    delete markersMap[id];
                }
            }

            for (const item of items) {
                if (!item.latitude || !item.longitude) continue;
                if (!markersMap[item.id]) addMapMarker(item);
            }
        }

        function highlightCard(id) {
            const card = document.getElementById('card-' + id);
            if (card) {
                card.scrollIntoView({ behavior: 'smooth', block: 'center' });
                card.classList.add('card-highlight');
                setTimeout(() => { card.classList.remove('card-highlight'); }, 1500);
            }
        }

        function highlightMapMarker(id, enable) {
            const marker = markersMap[id];
            if (!marker) return;

            if (enable) {
                marker.setZIndexOffset(10000);
                const el = marker.getElement();
                if (el) {
                    const pin = el.querySelector('.custom-pin');
                    if (pin) pin.classList.add('pin-highlighted');
                }
            } else {
                marker.setZIndexOffset(0);
                const el = marker.getElement();
                if (el) {
                    const pin = el.querySelector('.custom-pin');
                    if (pin) pin.classList.remove('pin-highlighted');
                }
            }
        }

        function locateOnMap(id, lat, lon) {
            if (!lat || !lon) {
                showToast("Brak współrzędnych GPS dla tej oferty.");
                return;
            }
            if (currentViewMode === 'grid') {
                switchViewMode('split');
            }
            if (map) {
                map.flyTo([lat, lon], 15, { duration: 0.8 });
                const marker = markersMap[id];
                if (marker) {
                    setTimeout(() => { marker.openPopup(); }, 700);
                }
            }
        }

        // ========================
        // Gallery / lightbox
        // ========================
        let activeModalGallery = [];
        let activeModalIndex = 0;

        function previewCardThumb(cardId, src, thumbEl, idx, total) {
            const img = document.getElementById('card-img-' + cardId);
            if (img) img.src = src;
            const counter = document.getElementById('imgcount-' + cardId);
            if (counter && total) counter.innerText = `${idx + 1}/${total}`;
            if (thumbEl && thumbEl.parentElement) {
                thumbEl.parentElement.querySelectorAll('.card-thumb').forEach(t => t.classList.remove('active'));
                thumbEl.classList.add('active');
            }
        }

        function openListingGallery(itemId, startIndex) {
            const item = allListings.find(i => i.id === itemId);
            if (!item) return;
            const fallbackImg = "https://images.unsplash.com/photo-1580587771525-78b9dba3b914?auto=format&fit=crop&w=600&q=80";
            const gallery = (item.gallery_images && item.gallery_images.length > 0) ? item.gallery_images : [item.main_image_url || fallbackImg];
            activeModalGallery = gallery;
            activeModalIndex = Math.max(0, Math.min(startIndex || 0, gallery.length - 1));
            showModalImage();
            const m = document.getElementById('imgModal');
            if (m) m.classList.add('open');
        }

        function openImgModal(src) {
            activeModalGallery = [src];
            activeModalIndex = 0;
            showModalImage();
            const m = document.getElementById('imgModal');
            if (m) m.classList.add('open');
        }

        function showModalImage() {
            const img = document.getElementById('imgModalSrc');
            const cap = document.getElementById('imgModalCaption');
            if (!img || activeModalGallery.length === 0) return;
            img.src = activeModalGallery[activeModalIndex];
            if (cap) {
                cap.innerText = `${activeModalIndex + 1} / ${activeModalGallery.length}`;
            }
            const prevBtn = document.getElementById('imgModalPrev');
            const nextBtn = document.getElementById('imgModalNext');
            if (prevBtn) prevBtn.style.display = activeModalGallery.length > 1 ? 'flex' : 'none';
            if (nextBtn) nextBtn.style.display = activeModalGallery.length > 1 ? 'flex' : 'none';
        }

        function navModalGallery(direction) {
            if (activeModalGallery.length <= 1) return;
            activeModalIndex = (activeModalIndex + direction + activeModalGallery.length) % activeModalGallery.length;
            showModalImage();
        }

        function closeImgModal() {
            const m = document.getElementById('imgModal');
            if (m) m.classList.remove('open');
        }

        // ========================
        // Grid rendering
        // ========================
        function renderGrid(items) {
            const container = document.getElementById('listingsContainer');
            if (!container) return;

            const token = ++gridRenderToken;
            container.innerHTML = '';

            if (items.length === 0) {
                container.innerHTML = '<div style="text-align: center; padding: 60px 20px; color: var(--text-muted); font-size: var(--font-size-base);">Brak ofert spełniających aktywne kryteria wyszukiwania.</div>';
                return;
            }

            const CHUNK = 48;
            let i = 0;
            const step = () => {
                if (token !== gridRenderToken) return;
                const slice = items.slice(i, i + CHUNK);
                container.insertAdjacentHTML('beforeend', slice.map(buildCardHtml).join(''));
                i += CHUNK;
                if (i < items.length) requestAnimationFrame(step);
            };
            requestAnimationFrame(step);
        }

        function renderGridIncremental(items, changedSet) {
            const container = document.getElementById('listingsContainer');
            if (!container) return;

            if (items.length === 0) {
                gridRenderToken++;
                container.innerHTML = '<div style="text-align: center; padding: 60px 20px; color: var(--text-muted); font-size: var(--font-size-base);">Brak ofert spełniających aktywne kryteria wyszukiwania.</div>';
                return;
            }

            if (!container.querySelector('article.card') || changedSet.size > 60) {
                renderGrid(items);
                return;
            }

            gridRenderToken++;

            const wantedIds = items.map(i => i.id);
            const wantedSet = new Set(wantedIds);

            container.querySelectorAll('article.card').forEach(n => {
                const cardId = parseInt(n.id.replace('card-', ''), 10);
                if (!wantedSet.has(cardId)) n.remove();
            });

            items.forEach(item => {
                const existing = document.getElementById('card-' + item.id);
                if (!existing) {
                    const html = buildCardHtml(item);
                    const idx = wantedIds.indexOf(item.id);
                    let ref = null;
                    for (let j = idx + 1; j < wantedIds.length; j++) {
                        ref = document.getElementById('card-' + wantedIds[j]);
                        if (ref) break;
                    }
                    const tmp = document.createElement('div');
                    tmp.innerHTML = html;
                    if (tmp.firstElementChild) container.insertBefore(tmp.firstElementChild, ref);
                } else if (changedSet.has(item.id)) {
                    const html = buildCardHtml(item);
                    const tmp = document.createElement('div');
                    tmp.innerHTML = html;
                    if (tmp.firstElementChild) existing.replaceWith(tmp.firstElementChild);
                }
            });

            let cursor = container.firstElementChild;
            for (const id of wantedIds) {
                const node = document.getElementById('card-' + id);
                if (!node) continue;
                if (node !== cursor) container.insertBefore(node, cursor);
                cursor = node.nextElementSibling;
            }
        }

        // ========================
        // Card builder
        // ========================
        function svgIcon(name, size = 13) {
            const s = `width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"`;
            const icons = {
                'star': `<svg ${s}><path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"></path></svg>`,
                'calendar': `<svg ${s}><path d="M8 2v4"></path><path d="M16 2v4"></path><rect width="18" height="18" x="3" y="4" rx="2"></rect><path d="M3 10h18"></path></svg>`,
                'check': `<svg ${s}><path d="M20 6 9 17l-5-5"></path></svg>`,
                'x': `<svg ${s}><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>`,
                'note': `<svg ${s}><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z"></path><path d="M14 2v4a2 2 0 0 0 2 2h4"></path><path d="M16 13H8"></path><path d="M16 17H8"></path><path d="M10 9H8"></path></svg>`,
                'map-pin': `<svg ${s}><path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"></path><circle cx="12" cy="10" r="3"></circle></svg>`,
                'shield': `<svg ${s}><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"></path><path d="m9 12 2 2 4-4"></path></svg>`,
                'external': `<svg ${s}><path d="M15 3h6v6"></path><path d="M10 14 21 3"></path><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path></svg>`,
                'chevron-down': `<svg ${s}><path d="m6 9 6 6 6-6"></path></svg>`,
                'more': `<svg ${s}><circle cx="12" cy="12" r="1"></circle><circle cx="19" cy="12" r="1"></circle><circle cx="5" cy="12" r="1"></circle></svg>`,
                'plug': `<svg ${s}><path d="M12 22v-5"></path><path d="M9 8V2"></path><path d="M15 8V2"></path><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"></path></svg>`,
                'copy': `<svg ${s}><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>`,
                'alert-triangle': `<svg ${s}><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><path d="M12 9v4"></path><path d="M12 17h.01"></path></svg>`
            };
            return icons[name] || '';
        }

        function buildCardHtml(item) {
            const fallbackImg = "https://images.unsplash.com/photo-1580587771525-78b9dba3b914?auto=format&fit=crop&w=600&q=80";

            let badgeClass = "badge-rejected";
            let badgeLabel = "Odrzucona";

            if (item.qualification_status === 'QUALIFIED_WHITELIST') {
                badgeClass = "badge-whitelist";
                badgeLabel = "Whitelist";
            } else if (item.is_qualified) {
                badgeClass = "badge-qualified";
                badgeLabel = "Zakwalifikowana";
            } else if (item.qualification_status === 'NEEDS_REVIEW') {
                badgeClass = "badge-review";
                badgeLabel = "Do weryfikacji";
            } else if (item.qualification_status === 'NEEDS_REVIEW_BORDERLINE') {
                badgeClass = "badge-review";
                badgeLabel = "Graniczna";
            }

            let cardCrmClass = "";
            if (item.user_status === 'FAVORITE') {
                cardCrmClass = "is-favorite";
            } else if (item.user_status === 'TO_VISIT') {
                cardCrmClass = "is-tovisit";
            } else if (item.user_status === 'CHECKED') {
                cardCrmClass = "is-checked";
            } else if (item.user_status === 'REJECTED') {
                cardCrmClass = "is-rejected";
            }

            // Delta badges join the main badge in the left topbar group
            let deltaBadge = '';
            let deltaPill = '';
            if (item.is_new_cycle) {
                deltaBadge = `<span class="card-badge badge-new">Nowa</span>`;
                deltaPill = `<span class="meta-tag tag-exact">Nowa</span>`;
            } else if (item.price_drop_amount && item.price_drop_amount > 0) {
                deltaBadge = `<span class="card-badge badge-updated">−${item.price_drop_amount.toLocaleString('pl-PL')} zł</span>`;
                deltaPill = `<span class="meta-tag tag-profile">Korekta −${item.price_drop_pct}%</span>`;
            } else if (item.is_updated_cycle) {
                deltaBadge = `<span class="card-badge badge-updated">Korekta danych</span>`;
                deltaPill = `<span class="meta-tag tag-profile">Zaktualizowana</span>`;
            } else if (item.user_status === 'CHECKED') {
                deltaBadge = `<span class="card-badge badge-checked">Sprawdzona</span>`;
            }

            const plotText = item.area_plot ? `${Math.round(item.area_plot)} m²` : '';
            const imgSrc = item.main_image_url || fallbackImg;

            const prosHtml = (item.pros || []).slice(0, 2).map(p => `<li>${escapeHtml(p)}</li>`).join('');
            const consHtml = (item.cons || []).slice(0, 1).map(c => `<li class="warning">${escapeHtml(c)}</li>`).join('');

            const precisionTag = item.is_exact_coords
                ? `<span class="loc-precision tag-exact">Dokładna</span>`
                : `<span class="loc-precision tag-approx">Rejon</span>`;

            const notesBadge = item.user_notes ? ` (1)` : '';

            const cat = item.category || 'dom';
            const catLabel = cat === 'mieszkanie' ? 'Mieszkanie' : (cat === 'dzialka' ? 'Działka' : 'Dom');
            const profileBadge = item.profile_name ? `<span class="meta-tag tag-profile">${escapeHtml(item.profile_name)}</span>` : '';
            const ownerBadge = item.is_private_owner === true ? `<span class="meta-tag tag-exact">Prywatne</span>` : (item.is_private_owner === false ? `<span class="meta-tag tag-approx">Biuro / deweloper</span>` : '');

            let rejectionHtml = "";
            if (item.filter_reasons && item.filter_reasons.length > 0 && !item.is_qualified) {
                rejectionHtml = `
                    <div class="rejection-box">
                        <span class="rejection-label">Kryterium wykluczające</span>
                        <ul>${item.filter_reasons.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul>
                    </div>
                `;
            }

            const marketText = item.market && item.market !== 'nieokreślony' ? escapeHtml(item.market) : '';
            const finishText = item.finish_condition && item.finish_condition !== 'nieokreślony' ? escapeHtml(item.finish_condition) : '';
            const sewText = item.sewerage && item.sewerage !== 'nieznana' ? escapeHtml(item.sewerage) : '';
            const heatText = item.heating && item.heating !== 'nieznane' ? escapeHtml(item.heating) : '';
            const roadText = item.access_road_type && item.access_road_type !== 'nieznana' ? escapeHtml(item.access_road_type) : '';
            const visTag = item.has_visualisations ? `<span class="meta-tag tag-vis">Wizualizacje</span>` : '';
            const mpzpZoneText = item.mpzp_zone ? escapeHtml(item.mpzp_zone.length > 25 ? item.mpzp_zone.slice(0, 25) + '…' : item.mpzp_zone) : '';
            const floodWarn = item.flood_risk_zone === 'ZAGROZENIE_POWODZIOWE';

            // Fixed 3×3 technical grid — always exactly 9 cells, '—' fallback for missing data
            const specCell = (label, value) => {
                const has = value !== null && value !== undefined && String(value).trim() !== '';
                return `<div class="spec-cell"><span class="spec-label">${label}</span><span class="spec-value${has ? '' : ' spec-value-empty'}">${has ? value : '—'}</span></div>`;
            };

            const specsHtml = [
                specCell('Dom', item.area_home > 0 ? `${item.area_home.toFixed(1)} m²` : ''),
                specCell('Działka', plotText),
                specCell('Zabudowa', item.building_type ? escapeHtml(item.building_type) : ''),
                specCell('Rynek', marketText),
                specCell('Stan', finishText),
                specCell('Ogrzewanie', heatText),
                specCell('Ścieki', sewText),
                specCell('Dojazd', roadText),
                specCell('MPZP', mpzpZoneText),
            ].join('');

            const floodHtml = floodWarn
                ? `<div class="card-flood-warning">${svgIcon('alert-triangle')} Teren zalewowy — zagrożenie powodziowe (ISOK)</div>`
                : '';

            const gallery = item.gallery_images || [];
            const galleryCount = gallery.length > 0 ? gallery.length : 1;
            const galleryCountBadge = galleryCount > 1
                ? `<span class="card-media-count num" id="imgcount-${item.id}">1/${galleryCount}</span>`
                : '';

            let galleryThumbnailsHtml = '';
            if (gallery.length > 1) {
                const thumbs = gallery.slice(0, 5).map((imgUrl, idx) => `
                    <img src="${escapeHtml(imgUrl)}" class="card-thumb ${idx === 0 ? 'active' : ''}"
                         alt="Miniatura ${idx + 1}" loading="lazy"
                         onmouseenter="previewCardThumb(${item.id}, '${escapeHtml(imgUrl)}', this, ${idx}, ${gallery.length})"
                         onclick="event.stopPropagation(); openListingGallery(${item.id}, ${idx})"
                         onerror="this.style.display='none'">
                `).join('');
                const moreCount = gallery.length - 5;
                const moreHtml = moreCount > 0 ? `<span class="thumb-more" onclick="event.stopPropagation(); openListingGallery(${item.id}, 5)">+${moreCount}</span>` : '';
                galleryThumbnailsHtml = `<div class="card-gallery-strip">${thumbs}${moreHtml}</div>`;
            }

            // Market delta (technical label, normalized for finish condition)
            let devBadge = '';
            if (item.price_deviation_pct !== null && item.price_deviation_pct !== undefined && item.market_median_m2) {
                const devRaw = item.price_deviation_pct;
                const dev = (item.price_deviation_adjusted_pct !== null && item.price_deviation_adjusted_pct !== undefined)
                    ? item.price_deviation_adjusted_pct
                    : devRaw;
                const medFmt = Math.round(item.market_median_m2).toLocaleString('pl-PL');
                const corrNote = (dev !== devRaw)
                    ? ` — po korekcie o stan wykończenia: ${dev > 0 ? '+' : ''}${dev}% (surowe: ${devRaw > 0 ? '+' : ''}${devRaw}%)`
                    : '';
                if (dev <= -4.0) {
                    devBadge = `<span class="market-delta dev-low" title="Mediana rynku: ${medFmt} zł/m²${corrNote} — wycena poniżej mediany">${dev > 0 ? '+' : ''}${dev}% vs rynek</span>`;
                } else if (dev >= 8.0) {
                    devBadge = `<span class="market-delta dev-high" title="Mediana rynku: ${medFmt} zł/m²${corrNote} — wycena powyżej mediany">+${dev}% vs rynek</span>`;
                } else {
                    devBadge = `<span class="market-delta dev-fair" title="Mediana rynku: ${medFmt} zł/m²${corrNote} — wycena w normie">${dev > 0 ? '+' : ''}${dev}% vs rynek</span>`;
                }
            }

            const priceDropHtml = item.price_drop_amount
                ? `<span class="price-drop num" title="Skumulowana obniżka ceny">−${item.price_drop_amount.toLocaleString('pl-PL')} zł (${item.price_drop_pct}%)</span>`
                : '';

            const tcoSub = (item.land_audit && item.land_audit.tco_audit)
                ? `<span class="card-action-sub num">CAPEX ~${formatPrice(item.land_audit.tco_audit.total_acquisition_cost)}</span>`
                : '';

            const geoportalHref = item.geoportal_url
                ? item.geoportal_url
                : (item.latitude && item.longitude
                    ? `https://mapy.geoportal.gov.pl/imap/Imgp_2.html?locale=pl&gui=new&session=%7B%22actions%22%3A%5B%7B%22name%22%3A%22locatePoint%22%2C%22params%22%3A%7B%22x%22%3A${item.longitude}%2C%22y%22%3A${item.latitude}%2C%22srid%22%3A4326%7D%7D%5D%7D`
                    : null);

            const gesutUrl = item.gesut_url || geoportalHref;

            const crmMenu = `
                <div class="card-action-menu">
                    <button class="card-action" onclick="toggleCardMenu(event, ${item.id})" title="Akcje CRM">
                        ${svgIcon('more')} Akcje ${svgIcon('chevron-down', 11)}
                    </button>
                    <div class="menu-popover" id="cardmenu-${item.id}">
                        <button class="menu-item ${item.user_status === 'FAVORITE' ? 'active' : ''}" onclick="toggleStatus(${item.id}, 'FAVORITE')">${svgIcon('star')} Ulubione</button>
                        <button class="menu-item ${item.user_status === 'TO_VISIT' ? 'active' : ''}" onclick="toggleStatus(${item.id}, 'TO_VISIT')">${svgIcon('calendar')} Do wizyty</button>
                        <button class="menu-item ${item.user_status === 'CHECKED' ? 'active' : ''}" onclick="toggleStatus(${item.id}, 'CHECKED')">${svgIcon('check')} Oznacz jako sprawdzone</button>
                        <button class="menu-item" onclick="toggleNotes(${item.id})">${svgIcon('note')} Notatka${notesBadge}</button>
                        ${gesutUrl ? `<a class="menu-item" href="${escapeHtml(gesutUrl)}" target="_blank" rel="noopener noreferrer" title="Uzbrojenie terenu GESUT (woda, prąd, gaz, kanalizacja)">${svgIcon('plug')} Uzbrojenie GESUT</a>` : ''}
                        <button class="menu-item" onclick="locateOnMap(${item.id}, ${item.latitude || 'null'}, ${item.longitude || 'null'})">${svgIcon('map-pin')} Pokaż na mapie</button>
                        <button class="menu-item danger ${item.user_status === 'REJECTED' ? 'active' : ''}" onclick="toggleStatus(${item.id}, 'REJECTED')">${svgIcon('x')} ${item.user_status === 'REJECTED' ? 'Przywróć' : 'Odrzuć'}</button>
                    </div>
                </div>
            `;

            return `
            <article class="card ${cardCrmClass}" id="card-${item.id}" onmouseenter="highlightMapMarker(${item.id}, true)" onmouseleave="highlightMapMarker(${item.id}, false)">
                <div class="card-media" onclick="openListingGallery(${item.id}, 0)">
                    <img id="card-img-${item.id}" src="${escapeHtml(imgSrc)}" alt="Zdjęcie nieruchomości" loading="lazy" onerror="this.src='${fallbackImg}'">
                    ${galleryCountBadge}
                    <div class="card-media-topbar">
                        <div class="card-badges-group">
                            <span class="card-badge ${badgeClass}">${badgeLabel}</span>
                            ${deltaBadge}
                        </div>
                        <button type="button" class="card-fav-btn ${item.user_status === 'FAVORITE' ? 'active' : ''}" onclick="event.stopPropagation(); toggleStatus(${item.id}, 'FAVORITE')" title="Ulubione">
                            ${item.user_status === 'FAVORITE' ? '★' : '☆'}
                        </button>
                    </div>
                </div>
                ${galleryThumbnailsHtml}
                <div class="card-content">
                    <div class="card-meta-row">
                        <span class="meta-source"><b>${catLabel}</b> · ${escapeHtml(item.portal).toUpperCase()} · #${escapeHtml(item.portal_id)}</span>
                        ${profileBadge}
                        ${ownerBadge}
                        ${visTag}
                        ${deltaPill}
                        <span class="meta-score">Score <strong>${Math.round(item.qualification_score)}</strong>/150</span>
                    </div>

                    <h3 class="card-title">
                        <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a>
                    </h3>

                    <div class="card-price-row">
                        <span class="price-main">${Math.round(item.price).toLocaleString('pl-PL')} zł</span>
                        <span class="price-m2">${Math.round(item.price_per_m2).toLocaleString('pl-PL')} zł/m²</span>
                        ${devBadge}
                        ${priceDropHtml}
                    </div>

                    <div class="card-location">
                        <span>${escapeHtml(item.street || item.district || item.city || item.location_raw || '')}</span>
                        ${precisionTag}
                    </div>

                    <div class="card-specs-grid-fixed">
                        ${specsHtml}
                    </div>

                    ${floodHtml}

                    ${rejectionHtml}

                    ${(prosHtml || consHtml) ? `<div class="card-features"><ul>${prosHtml}${consHtml}</ul></div>` : ''}

                    <div class="card-footer">
                        <button class="card-action primary" onclick="openAiModal(${item.id})" title="Raport audytu i due diligence">
                            ${svgIcon('shield')} Audyt ${tcoSub}
                        </button>
                        ${geoportalHref ? `
                        <a href="${escapeHtml(geoportalHref)}" class="card-action" target="_blank" rel="noopener noreferrer" title="${item.parcel_id ? 'Działka katastralna: ' + escapeHtml(item.parcel_id) : 'Otwórz punkt w Geoportalu'}">
                            ${svgIcon('map-pin')} Geoportal
                        </a>` : ''}
                        <a href="${escapeHtml(item.url)}" class="card-action" target="_blank" rel="noopener noreferrer" title="Otwórz ogłoszenie źródłowe">
                            ${svgIcon('external')} Otwórz źródło
                        </a>
                        ${crmMenu}
                    </div>

                    <div class="notes-drawer" id="notes-${item.id}">
                        <textarea id="note-txt-${item.id}" placeholder="Prywatne notatki z oględzin, agent, ustalenia…">${escapeHtml(item.user_notes || '')}</textarea>
                        <div class="notes-footer">
                            <span class="notes-status-text" id="note-st-${item.id}"></span>
                            <button class="notes-save-btn" onclick="saveNote(${item.id})">Zapisz</button>
                        </div>
                    </div>
                </div>
            </article>
            `;
        }

        function toggleCardMenu(event, id) {
            event.stopPropagation();
            const m = document.getElementById('cardmenu-' + id);
            if (!m) return;
            const wasOpen = m.classList.contains('open');
            closeCardMenus();
            if (!wasOpen) m.classList.add('open');
        }

        function closeCardMenus() {
            document.querySelectorAll('.menu-popover.open').forEach(m => m.classList.remove('open'));
        }

        function escapeHtml(str) {
            if (!str) return '';
            return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
        }

        function formatPrice(val) {
            if (val === null || val === undefined || isNaN(val)) return '0 zł';
            return Math.round(Number(val)).toLocaleString('pl-PL') + ' zł';
        }

        // ========================
        // CRM actions
        // ========================
        async function toggleStatus(id, targetStatus) {
            const item = allListings.find(i => i.id === id);
            if (!item) return;
            const newStatus = (item.user_status === targetStatus) ? 'NEW' : targetStatus;
            await updateStatus(id, newStatus);
            closeCardMenus();
        }

        async function updateStatus(id, newStatus) {
            try {
                await Transport.updateStatus(id, newStatus);
                const item = allListings.find(i => i.id === id);
                if (item) item.user_status = newStatus;
                updateStats(allListings);
                applyFilters();
                showToast(`Status oferty #${id}: ${newStatus}`);
            } catch (err) {
                console.error("Status update failed:", err);
                showToast("Błąd zapisu statusu.");
            }
        }

        function toggleNotes(id) {
            const drawer = document.getElementById('notes-' + id);
            if (drawer) {
                drawer.style.display = (drawer.style.display === 'block') ? 'none' : 'block';
            }
            closeCardMenus();
        }

        async function saveNote(id) {
            const txt = document.getElementById('note-txt-' + id).value;
            const stLabel = document.getElementById('note-st-' + id);
            stLabel.innerText = "Zapisywanie…";

            try {
                await Transport.updateNotes(id, txt);
                const item = allListings.find(i => i.id === id);
                if (item) item.user_notes = txt;
                stLabel.innerText = "Zapisano";
                showToast("Notatka zapisana.");
                setTimeout(() => { stLabel.innerText = ""; }, 2000);
            } catch (err) {
                stLabel.innerText = "Błąd zapisu";
                showToast("Nie udało się zapisać notatki.");
            }
        }

        // ========================
        // Scraping state & monitoring
        // ========================
        let scrapePollTimer = null;

        function copyParcelCadastre(listingId) {
            const item = (typeof listingId === 'object' && listingId !== null)
                ? listingId
                : (allListings.find(i => i.id === listingId) || currentAiItem);
            if (!item || !item.parcel_id) return;
            navigator.clipboard.writeText(item.parcel_id).then(() => {
                showToast(`Skopiowano identyfikator działki: ${item.parcel_id}`);
            }).catch(() => {});
        }

        function formatLogEntry(l) {
            const time = escapeHtml(l.time || '');
            const rawMsg = l.message || '';
            const level = l.level || 'info';

            let portalBadge = '';
            let msgText = rawMsg;
            const portalMatch = rawMsg.match(/^\[([^\]]+)\]\s*(.*)$/);
            if (portalMatch) {
                portalBadge = `<span class="log-portal">${escapeHtml(portalMatch[1])}</span>`;
                msgText = portalMatch[2];
            }

            let levelBadge = '';
            if (level === 'error') {
                levelBadge = `<span class="log-level-badge log-level-error">BŁĄD</span>`;
            } else if (level === 'warning') {
                levelBadge = `<span class="log-level-badge log-level-warning">UWAGA</span>`;
            } else if (level === 'success') {
                levelBadge = `<span class="log-level-badge log-level-success">NOWA</span>`;
            }

            let escapedMsg = escapeHtml(msgText);
            escapedMsg = escapedMsg.replace(/(\d[\d\s,.]*\s*(?:zł|PLN|m²|m2))/g, '<strong>$1</strong>');

            return `
                <div class="log-row">
                    <span class="log-time">${time}</span>
                    ${levelBadge}
                    ${portalBadge}
                    <span class="log-msg">${escapedMsg}</span>
                </div>
            `;
        }

        function renderScrapeStatus(st) {
            const panel = document.getElementById('progressPanel');
            const btnScrape = document.getElementById('btnScrape');
            const btnCancel = document.getElementById('btnCancelScrape');

            if (!panel || !st) return;

            const pct = Math.min(100, Math.max(0, st.percentage || 0));
            document.getElementById('progPercent').innerText = pct + '%';
            document.getElementById('progBar').style.width = pct + '%';
            document.getElementById('progStep').innerText = st.current_step || 'Przetwarzanie…';
            document.getElementById('progPortal').innerText = st.current_portal ? `Aktywny: ${st.current_portal}` : 'Inicjalizacja…';

            document.getElementById('progScraped').innerText = st.items_scraped || 0;
            document.getElementById('progQualified').innerText = st.items_qualified || 0;
            document.getElementById('progDups').innerText = st.duplicates_found || 0;
            const elapsed = st.elapsed_seconds || 0;
            document.getElementById('progElapsed').innerText =
                elapsed >= 60 ? `${Math.floor(elapsed / 60)}m ${elapsed % 60}s` : `${elapsed}s`;

            if (st.logs && st.logs.length > 0) {
                const logsHtml = st.logs.map(formatLogEntry).join('');
                const logBox = document.getElementById('progLogs');
                if (logBox) {
                    logBox.innerHTML = logsHtml;
                    logBox.scrollTop = logBox.scrollHeight;
                }
            }

            if (btnCancel) {
                if (st.is_running) {
                    btnCancel.style.display = 'inline-flex';
                    if (st.cancel_requested) {
                        btnCancel.disabled = true;
                        btnCancel.innerText = 'Zatrzymywanie…';
                    } else {
                        btnCancel.disabled = false;
                        btnCancel.innerText = 'Zatrzymaj';
                    }
                } else {
                    btnCancel.style.display = 'none';
                }
            }

            if (btnScrape) {
                if (st.is_running) {
                    btnScrape.disabled = true;
                    btnScrape.innerHTML = st.cancel_requested ? 'Zatrzymywanie…' : 'Synchronizacja w toku…';
                } else {
                    btnScrape.disabled = false;
                    btnScrape.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v14a9 3 0 0 0 18 0V5"></path><path d="M3 12a9 3 0 0 0 18 0"></path></svg><span class="btn-label">Synchronizuj bazę</span>';
                }
            }
        }

        function startScrapeMonitor() {
            if (scrapePollTimer) return;
            const panel = document.getElementById('progressPanel');
            if (panel) panel.style.display = 'block';

            scrapePollTimer = setInterval(async () => {
                try {
                    const st = await Transport.scrapeStatus();
                    if (!st || typeof st !== 'object') return;
                    renderScrapeStatus(st);

                    if (!st.is_running) {
                        clearInterval(scrapePollTimer);
                        scrapePollTimer = null;

                        const btnScrape = document.getElementById('btnScrape');
                        if (btnScrape) {
                            btnScrape.disabled = false;
                            btnScrape.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v14a9 3 0 0 0 18 0V5"></path><path d="M3 12a9 3 0 0 0 18 0"></path></svg><span class="btn-label">Synchronizuj bazę</span>';
                        }
                        const btnCancel = document.getElementById('btnCancelScrape');
                        if (btnCancel) btnCancel.style.display = 'none';

                        if (st.cancel_requested || (st.current_step && st.current_step.includes('Zatrzymano'))) {
                            showToast("Synchronizacja została przerwana przez użytkownika.");
                        } else {
                            showToast(`Synchronizacja zakończona. Pobrane: ${st.items_scraped || 0}, zakwalifikowane: ${st.items_qualified || 0}`);
                        }
                        await fetchListings();
                    }
                } catch (e) {
                    console.error("Error polling scrape status:", e);
                }
            }, 600);
        }

        async function checkActiveScrape() {
            try {
                const st = await Transport.scrapeStatus();
                if (st && st.is_running) {
                    const panel = document.getElementById('progressPanel');
                    if (panel) panel.style.display = 'block';
                    renderScrapeStatus(st);
                    startScrapeMonitor();
                }
            } catch (e) {
                console.debug("Could not check active scrape status:", e);
            }
        }

        async function triggerScrape() {
            const btn = document.getElementById('btnScrape');
            const panel = document.getElementById('progressPanel');
            if (btn) {
                btn.disabled = true;
                btn.innerText = "Inicjalizacja…";
            }
            if (panel) panel.style.display = 'block';

            const curProf = allProfiles.find(p => p.id === selectedProfileId);
            const profName = curProf ? curProf.name : 'Wszystkie profile';
            showToast(`Rozpoczynanie synchronizacji (${profName})…`);

            try {
                const out = await Transport.startScrape(selectedProfileId);
                if (out.conflict) {
                    showToast("Synchronizacja jest już w toku.");
                }
                startScrapeMonitor();
            } catch (err) {
                showToast("Błąd podczas uruchamiania synchronizacji: " + err);
                if (btn) {
                    btn.disabled = false;
                    btn.innerText = "Synchronizuj bazę";
                }
            }
        }

        async function cancelScrape() {
            const btnCancel = document.getElementById('btnCancelScrape');
            if (btnCancel) {
                btnCancel.disabled = true;
                btnCancel.innerText = "Zatrzymywanie…";
            }
            showToast("Żądanie zatrzymania synchronizacji…");

            try {
                const out = await Transport.cancelScrape();
                if (out.status === 'not_running') {
                    showToast("Synchronizacja nie jest obecnie uruchomiona.");
                }
            } catch (e) {
                showToast("Nie udało się wysłać żądania zatrzymania.");
            }
        }

        // ========================
        // Due Diligence drawer content (land audit)
        // ========================
        function renderLandAuditHtml(item) {
            if (!item) return '';
            const audit = item.land_audit || {};
            const tco = audit.tco_audit || null;
            const commute = audit.commute_audit || null;
            const risk = audit.risk_shield || null;
            const gesut = audit.gesut_audit || null;
            const packet = audit.cadastral_packet || audit.search_packet || {
                parcel_id: item.parcel_id || '',
                parcel_short: (item.parcel_id || '').split('.').pop() || '',
                voivodeship: '',
                cadastral_area: item.cadastral_area || null
            };

            // 1. Legal & planning parameters
            let legalRows = '';
            if (item.parcel_id) {
                const areaTxt = item.cadastral_area ? ` (${item.cadastral_area} m²)` : '';
                legalRows += `
                    <tr>
                        <th>Identyfikator działki</th>
                        <td class="value"><span class="num">${escapeHtml(item.parcel_id)}</span>${areaTxt}
                            <button type="button" class="copy-inline-btn" onclick="copyParcelCadastre(${item.id})" title="Kopiuj identyfikator do schowka">
                                ${svgIcon('copy', 10)} Kopiuj
                            </button>
                        </td>
                    </tr>`;
            }
            if (packet.voivodeship) {
                legalRows += `<tr><th>Województwo</th><td class="value">${escapeHtml(packet.voivodeship)}</td></tr>`;
            }
            if (item.mpzp_zone) {
                const isMnp = item.mpzp_status === 'OBOWIĄZUJĄCY';
                const statusTag = isMnp
                    ? `<span class="meta-tag tag-exact">Obowiązujący</span>`
                    : `<span class="meta-tag tag-vis">Wymaga WZ</span>`;
                legalRows += `<tr${isMnp ? '' : ' class="row-warn"'}><th>MPZP</th><td class="value">${escapeHtml(item.mpzp_zone)} ${statusTag}</td></tr>`;
            } else {
                legalRows += `<tr class="row-warn"><th>MPZP</th><td class="value">Brak planu miejscowego (wymaga WZ)</td></tr>`;
            }
            if (item.flood_risk_zone) {
                const isFlood = item.flood_risk_zone === 'ZAGROŻENIE_POWODZIOWE';
                legalRows += `<tr class="${isFlood ? 'row-danger' : 'row-ok'}"><th>Ryzyko powodziowe</th><td class="value">${isFlood ? 'Zagrożenie powodziowe (ISOK)' : 'Brak zagrożenia (ISOK)'}</td></tr>`;
            }

            const legalHtml = legalRows ? `
                <div class="audit-block">
                    <div class="audit-block-head">
                        <div class="audit-block-title">Parametry prawne i planistyczne</div>
                    </div>
                    <table class="dd-table">${legalRows}</table>
                </div>
            ` : '';

            // 2. CAPEX (TCO) as clean financial table
            let tcoHtml = '';
            if (tco) {
                const breakdownRows = (tco.breakdown || []).map(b => `
                    <tr>
                        <td><strong>${escapeHtml(b.item)}</strong></td>
                        <td class="amount">${formatPrice(b.amount)}</td>
                        <td class="note">${escapeHtml(b.desc)}</td>
                    </tr>
                `).join('');

                let negoNoteHtml = '';
                if (tco && tco.hidden_costs_total !== undefined && tco.hidden_costs_total !== null) {
                    const finCost = (typeof tco.finishing_cost === 'number') ? tco.finishing_cost : 0;
                    const txCost = (typeof tco.transaction_costs === 'number')
                        ? tco.transaction_costs
                        : Math.max(0, tco.hidden_costs_total - finCost);
                    if (finCost > 0) {
                        negoNoteHtml = `
                            <strong>Czynniki korygujące wycenę:</strong>
                            wykończenie wnętrz <strong class="num">+${formatPrice(finCost)}</strong>,
                            koszty transakcyjne (PCC, notariusz, prowizja) <strong class="num">+${formatPrice(txCost)}</strong>
                            — łącznie <strong class="num">+${formatPrice(tco.hidden_costs_total)}</strong> (+${tco.hidden_costs_pct}% ceny ofertowej).
                            Dane te stanowią podstawę argumentacji cenowej w negocjacjach.`;
                    } else {
                        negoNoteHtml = `
                            <strong>Brak nakładów na wykończenie</strong> (stan do zamieszkania) — koszty wejścia to wyłącznie
                            koszty transakcyjne (PCC, notariusz, prowizja): <strong class="num">+${formatPrice(txCost)}</strong>
                            (+${tco.hidden_costs_pct}% ceny ofertowej).
                            Dane te stanowią podstawę argumentacji cenowej w negocjacjach.`;
                    }
                }

                tcoHtml = `
                    <div class="audit-block">
                        <div class="audit-block-head">
                            <div class="audit-block-title">Struktura kosztów całkowitych (CAPEX)</div>
                            <span class="audit-verdict-badge ${getSeverityBadgeClass(tco.severity)}">${escapeHtml(tco.verdict)}</span>
                        </div>
                        <table class="capex-table">
                            <thead>
                                <tr><th>Pozycja kosztowa</th><th>Szacunek</th><th>Podstawa</th></tr>
                            </thead>
                            <tbody>
                                ${breakdownRows}
                                <tr class="total">
                                    <td>Suma nakładów kapitałowych</td>
                                    <td class="amount">${formatPrice(tco.total_acquisition_cost)}</td>
                                    <td class="note">Koszt zakupu + podatki + opłaty + adaptacja</td>
                                </tr>
                            </tbody>
                        </table>
                        <div class="nego-note">${negoNoteHtml}</div>
                    </div>
                `;
            }

            // 3. Commute
            let commuteHtml = '';
            if (commute) {
                const commuteFindings = (commute.findings || []).map(f => `
                    <div class="audit-finding-item">
                        <span class="audit-dot d-${f.severity === 'danger' ? 'danger' : (f.severity === 'warning' ? 'warning' : (f.severity === 'success' ? 'success' : 'info'))}"></span>
                        <div class="audit-finding-body">
                            <div class="audit-finding-title">${f.badge ? `<span class="audit-finding-badge">${escapeHtml(f.badge)}</span>` : ''}${escapeHtml(f.title)}</div>
                            <div class="audit-finding-desc">${escapeHtml(f.desc)}</div>
                        </div>
                    </div>
                `).join('');

                commuteHtml = `
                    <div class="audit-block">
                        <div class="audit-block-head">
                            <div class="audit-block-title">Dostępność komunikacyjna</div>
                            <span class="audit-verdict-badge ${getSeverityBadgeClass(commute.severity)}">${escapeHtml(commute.verdict)}</span>
                        </div>
                        <div class="audit-finding-list">${commuteFindings}</div>
                        <div class="audit-actions">
                            ${(item.latitude && item.longitude) ? `
                            <a href="https://www.google.com/maps/dir/?api=1&destination=${item.latitude},${item.longitude}" target="_blank" rel="noopener noreferrer" class="audit-link-btn" title="Wyznacz trasę dojazdu w Google Maps">
                                ${svgIcon('map-pin')} Nawiguj w Google Maps
                            </a>` : ''}
                            ${geoUrlOf(item) ? `
                            <a href="${escapeHtml(geoUrlOf(item))}" target="_blank" rel="noopener noreferrer" class="audit-link-btn" title="Pokaż w Geoportalu">
                                ${svgIcon('external')} Geoportal
                            </a>` : ''}
                        </div>
                    </div>
                `;
            }

            // 4. Legal & planning risk shield
            let riskHtml = '';
            if (risk) {
                const riskFindings = (risk.findings || []).map(f => `
                    <div class="audit-finding-item">
                        <span class="audit-dot d-${f.severity === 'danger' ? 'danger' : (f.severity === 'warning' ? 'warning' : (f.severity === 'success' ? 'success' : 'info'))}"></span>
                        <div class="audit-finding-body">
                            <div class="audit-finding-title">${f.badge ? `<span class="audit-finding-badge">${escapeHtml(f.badge)}</span>` : ''}${escapeHtml(f.title)}</div>
                            <div class="audit-finding-desc">${escapeHtml(f.desc)}</div>
                        </div>
                    </div>
                `).join('');

                riskHtml = `
                    <div class="audit-block">
                        <div class="audit-block-head">
                            <div class="audit-block-title">Ryzyka prawne i planistyczne</div>
                            <span class="audit-verdict-badge ${getSeverityBadgeClass(risk.severity)}">${escapeHtml(risk.verdict)}</span>
                        </div>
                        <div class="audit-finding-list">${riskFindings}</div>
                        <div class="audit-actions">
                            ${item.parcel_id ? `
                            <button type="button" class="audit-copy-btn" onclick="copyParcelCadastre(${item.id})" title="Skopiuj identyfikator działki katastralnej">
                                ${svgIcon('copy', 11)} Kopiuj ID działki (${escapeHtml(packet.parcel_short || item.parcel_id)})
                            </button>` : ''}
                            ${geoUrlOf(item) ? `
                            <a href="${escapeHtml(geoUrlOf(item))}" target="_blank" rel="noopener noreferrer" class="audit-link-btn" title="Otwórz ewidencję gruntów EGiB">
                                ${svgIcon('external')} Ewidencja gruntów (EGiB)
                            </a>` : ''}
                        </div>
                    </div>
                `;
            }

            // 5. GESUT
            let gesutHtml = '';
            if (gesut) {
                const gesutFindings = (gesut.findings || []).map(f => `
                    <div class="audit-finding-item">
                        <span class="audit-dot d-${f.severity === 'danger' ? 'danger' : (f.severity === 'warning' ? 'warning' : (f.severity === 'success' ? 'success' : 'info'))}"></span>
                        <div class="audit-finding-body">
                            <div class="audit-finding-title">${f.badge ? `<span class="audit-finding-badge">${escapeHtml(f.badge)}</span>` : ''}${escapeHtml(f.title)}</div>
                            <div class="audit-finding-desc">${escapeHtml(f.desc)}</div>
                        </div>
                    </div>
                `).join('');

                const gesutUrl = item.gesut_url || geoUrlOf(item);
                const gesutSource = gesut.source
                    ? `<div class="gesut-source"><span class="audit-dot d-info"></span>${escapeHtml(gesut.source)}</div>`
                    : '';

                gesutHtml = `
                    <div class="audit-block">
                        <div class="audit-block-head">
                            <div class="audit-block-title">Uzbrojenie terenu (GESUT)</div>
                            <span class="audit-verdict-badge ${getSeverityBadgeClass(gesut.severity)}">${escapeHtml(gesut.verdict)}</span>
                        </div>
                        <div class="audit-finding-list">${gesutFindings}</div>
                        ${gesutSource}
                        <div class="audit-actions">
                            ${gesutUrl ? `
                            <a href="${escapeHtml(gesutUrl)}" target="_blank" rel="noopener noreferrer" class="audit-link-btn" title="Otwórz Geoportal z warstwami uzbrojenia terenu KIUT">
                                ${svgIcon('external')} Geoportal (uzbrojenie KIUT)
                            </a>` : ''}
                            ${geoUrlOf(item) ? `
                            <a href="${escapeHtml(geoUrlOf(item))}" target="_blank" rel="noopener noreferrer" class="audit-link-btn" title="Otwórz ewidencję gruntów EGiB">
                                ${svgIcon('external')} Ewidencja gruntów (EGiB)
                            </a>` : ''}
                        </div>
                        <div class="gesut-legend-bar">
                            <span class="gesut-legend-pill"><b>e</b> = prąd</span>
                            <span class="gesut-legend-pill"><b>g</b> = gaz</span>
                            <span class="gesut-legend-pill"><b>w</b> = woda</span>
                            <span class="gesut-legend-pill"><b>k</b> = kanalizacja</span>
                            <span class="gesut-legend-pill"><b>t</b> = światłowód</span>
                        </div>
                    </div>
                `;
            }

            return `
                ${legalHtml}
                ${tcoHtml}
                ${commuteHtml}
                ${riskHtml}
                ${gesutHtml}
            `;
        }

        function geoUrlOf(item) {
            if (item.geoportal_url) return item.geoportal_url;
            if (item.latitude && item.longitude) {
                return `https://mapy.geoportal.gov.pl/imap/Imgp_2.html?locale=pl&gui=new&session=%7B%22actions%22%3A%5B%7B%22name%22%3A%22locatePoint%22%2C%22params%22%3A%7B%22x%22%3A${item.longitude}%2C%22y%22%3A${item.latitude}%2C%22srid%22%3A4326%7D%7D%5D%7D`;
            }
            return null;
        }

        function getSeverityBadgeClass(sev) {
            if (sev === 'danger') return 'audit-verdict-danger';
            if (sev === 'warning') return 'audit-verdict-warning';
            return 'audit-verdict-success';
        }

        // ========================
        // Due Diligence drawer
        // ========================
        let currentAiItem = null;

        function openAiModal(listingId) {
            const item = allListings.find(i => i.id === listingId);
            if (!item) return;
            currentAiItem = item;

            if (item.user_status === 'NEW') {
                updateStatus(item.id, 'CHECKED');
            }

            document.getElementById('aiModalTitle').innerText = item.title || '';

            // Recommendation
            const verdictSection = document.getElementById('aiVerdictSection');
            const verdictBadge = document.getElementById('aiVerdictBadge');
            const verdictContent = document.getElementById('aiVerdictContent');
            if (item.ai_verdict || item.worth_interest !== null && item.worth_interest !== undefined) {
                verdictSection.style.display = 'flex';
                if (item.worth_interest === true) {
                    verdictBadge.className = 'verdict-badge positive';
                    verdictBadge.innerHTML = '<span class="verdict-dot"></span>Rekomendacja: Pozytywna (Kwalifikuje się)';
                } else if (item.worth_interest === false) {
                    verdictBadge.className = 'verdict-badge negative';
                    verdictBadge.innerHTML = '<span class="verdict-dot"></span>Rekomendacja: Negatywna (Do odrzucenia)';
                } else {
                    verdictBadge.className = 'verdict-badge unknown';
                    verdictBadge.innerHTML = '<span class="verdict-dot"></span>Rekomendacja: Wymaga weryfikacji';
                }
                verdictContent.innerText = item.ai_verdict || 'Brak uzasadnienia rekomendacji.';
            } else {
                verdictSection.style.display = 'none';
            }

            // Synthesis
            const summaryEl = document.getElementById('aiSummaryContent');
            summaryEl.innerText = item.ai_summary || 'Brak analizy AI — uruchom synchronizację z włączonym LLM, aby wygenerować syntezę oferty.';

            // Spatial / financial / legal audit
            const spatialSection = document.getElementById('aiSpatialSection');
            const spatialContent = document.getElementById('aiSpatialContent');
            if (item.parcel_id || item.mpzp_zone || item.flood_risk_zone || item.geoportal_url || (item.latitude && item.longitude) || item.land_audit) {
                spatialSection.style.display = 'flex';
                spatialContent.innerHTML = renderLandAuditHtml(item);
            } else {
                spatialSection.style.display = 'none';
            }

            // Contact
            const contactSection = document.getElementById('aiContactSection');
            if (item.contact_phone || item.contact_person) {
                contactSection.style.display = 'flex';
                const phoneEl = document.getElementById('aiContactPhone');
                const personEl = document.getElementById('aiContactPerson');
                if (item.contact_phone) {
                    const cleanPhone = item.contact_phone.replace(/[\s-]/g, '');
                    phoneEl.href = 'tel:' + cleanPhone;
                    phoneEl.innerText = item.contact_phone;
                } else {
                    phoneEl.href = '';
                    phoneEl.innerText = '';
                }
                personEl.innerText = item.contact_person || '';
            } else {
                contactSection.style.display = 'none';
            }

            // Questions
            const qList = document.getElementById('aiQuestionsList');
            const questions = item.ai_questions || [];
            if (questions.length > 0) {
                qList.innerHTML = questions.map(q => `<li>${escapeHtml(q)}</li>`).join('');
            } else {
                qList.innerHTML = '<li class="no-data">Brak pytań — uruchom synchronizację z analizą LLM.</li>';
            }

            // CAPEX
            buildBudgetTable(item);

            // Price adjustment factors
            const negSection = document.getElementById('aiNegotiationSection');
            const negContent = document.getElementById('aiNegotiationContent');
            const btnCopyNeg = document.getElementById('btnCopyNegArgs');

            const leverage = item.negotiation_leverage || 'ŚREDNIA';
            const levMeta = {
                'WYSOKA': { cls: 'positive', label: 'Wysoka' },
                'ŚREDNIA': { cls: 'unknown', label: 'Średnia' },
                'NISKA': { cls: 'negative', label: 'Niska' }
            };
            const lev = levMeta[leverage] || levMeta['ŚREDNIA'];

            const medM2 = item.market_median_m2 ? Math.round(item.market_median_m2).toLocaleString('pl-PL') + ' zł/m²' : 'Brak danych';
            const devText = (item.price_deviation_pct !== null && item.price_deviation_pct !== undefined)
                ? (item.price_deviation_pct > 0 ? `+${item.price_deviation_pct}%` : `${item.price_deviation_pct}%`)
                : '—';

            const fmvText = item.fair_market_value ? Math.round(item.fair_market_value).toLocaleString('pl-PL') + ' zł' : '—';
            const openOfferText = item.suggested_opening_offer ? Math.round(item.suggested_opening_offer).toLocaleString('pl-PL') + ' zł' : '—';

            let diffText = '';
            if (item.price && item.suggested_opening_offer && item.price > item.suggested_opening_offer) {
                const diff = Math.round(item.price - item.suggested_opening_offer);
                const diffPct = Math.round((diff / item.price) * 100);
                diffText = `Rabat: −${diff.toLocaleString('pl-PL')} zł (−${diffPct}%)`;
            }

            const daysOnMkt = item.days_on_market ? `${item.days_on_market} dni` : '—';

            const args = item.negotiation_arguments || [];
            let argsHtml = '';
            if (args.length > 0) {
                argsHtml = `
                    <div class="nego-args">
                        <div class="nego-args-head">Argumenty korygujące cenę</div>
                        <ul>
                            ${args.map(a => `<li>${escapeHtml(a)}</li>`).join('')}
                        </ul>
                    </div>
                `;
                if (btnCopyNeg) btnCopyNeg.style.display = 'inline-flex';
            } else {
                if (btnCopyNeg) btnCopyNeg.style.display = 'none';
            }

            negContent.innerHTML = `
                <div class="nego-grid">
                    <div class="nego-tile">
                        <span class="nego-tile-lbl">Pozycja negocjacyjna</span>
                        <span class="nego-tile-val">${lev.label}</span>
                        <span class="nego-tile-sub">Na rynku: ${daysOnMkt}</span>
                    </div>
                    <div class="nego-tile">
                        <span class="nego-tile-lbl">Mediana rynku</span>
                        <span class="nego-tile-val num">${medM2}</span>
                        <span class="nego-tile-sub">Odchylenie: <strong>${devText}</strong></span>
                    </div>
                    <div class="nego-tile">
                        <span class="nego-tile-lbl">Wartość godziwa (FMV)</span>
                        <span class="nego-tile-val num">${fmvText}</span>
                        <span class="nego-tile-sub">Korygowana o stan i wady</span>
                    </div>
                    <div class="nego-tile">
                        <span class="nego-tile-lbl">Oferta otwarcia</span>
                        <span class="nego-tile-val num" style="color: var(--green-text);">${openOfferText}</span>
                        <span class="nego-tile-sub">${diffText || 'Zgodna z wyceną'}</span>
                    </div>
                </div>
                ${argsHtml}
            `;

            // Price corrections history
            const phSection = document.getElementById('aiPriceDropSection');
            const phCount = item.price_history_count || 0;
            if (phCount >= 2) {
                phSection.style.display = 'flex';
                const badgeEl = document.getElementById('aiPriceDropBadge');
                if (item.price_drop_amount) {
                    badgeEl.innerHTML = `<span class="ph-badge num">Korekta: −${item.price_drop_amount.toLocaleString('pl-PL')} zł (−${item.price_drop_pct}%)</span>`;
                } else {
                    badgeEl.innerHTML = '<span style="font-size:12px;color:var(--text-muted);">Cena bez zmian od pierwszego wpisu.</span>';
                }
                const timeline = document.getElementById('aiPriceTimeline');
                timeline.innerHTML = '<span style="font-size:12px;color:var(--text-muted);">Ładowanie historii cen…</span>';
                Transport.priceHistory(item.id)
                    .then(ph => {
                        if (!Array.isArray(ph) || ph.length < 2) {
                            phSection.style.display = 'none';
                            return;
                        }
                        timeline.innerHTML = ph.map(h => {
                            const d = h.date ? new Date(h.date).toLocaleDateString('pl-PL') : '—';
                            return `<div class="ph-entry"><span>${d}</span><span class="ph-price num">${Math.round(h.price).toLocaleString('pl-PL')} zł</span></div>`;
                        }).join('');
                    })
                    .catch(() => {
                        timeline.innerHTML = '<span style="font-size:12px;color:var(--text-muted);">Nie udało się pobrać historii cen.</span>';
                    });
            } else {
                phSection.style.display = 'none';
            }

            document.getElementById('aiModal').classList.add('open');
        }

        function closeAiModal(e) {
            if (e && e.target && e.target.id !== 'aiModal') return;
            document.getElementById('aiModal').classList.remove('open');
            currentAiItem = null;
        }

        function buildBudgetTable(item) {
            const price = item.price || 0;
            const market = (item.market || '').toLowerCase();
            const isPrimary = market.includes('pierwotny');
            const pcc = isPrimary ? 0 : Math.round(price * 0.02);
            const notaryBase = Math.min(10000, Math.max(100, Math.round(price * 0.005)));
            const vatNotary = Math.round(notaryBase * 0.23);
            const kwFee = 200;
            const notaryTotal = notaryBase + vatNotary + kwFee;

            let hiddenTotal = 0;
            const hiddenItems = [];
            (item.cons || []).forEach(c => {
                if (c.includes('[Ukryty koszt]')) {
                    const numMatch = c.match(/(\d[\d\s]*\d)\s*zł/);
                    if (numMatch) {
                        const val = parseInt(numMatch[1].replace(/\s/g, ''));
                        hiddenTotal += val;
                        hiddenItems.push({label: c.replace('[Ukryty koszt] ', ''), val});
                    } else {
                        hiddenItems.push({label: c.replace('[Ukryty koszt] ', ''), val: 0});
                    }
                }
            });

            const finish = (item.finish_condition || '').toLowerCase();
            let finishCostPerM2 = 0;
            let finishLabel = '';
            if (finish.includes('deweloperski') || finish.includes('wykonczenia')) {
                finishCostPerM2 = 1500;
                finishLabel = 'Adaptacja — wykończenie (~1 500 zł/m²)';
            } else if (finish.includes('surowy_zamkniety') || finish.includes('surowy zamknięty')) {
                finishCostPerM2 = 2500;
                finishLabel = 'Adaptacja — wykończenie od surowego (~2 500 zł/m²)';
            } else if (finish.includes('surowy_otwarty') || finish.includes('surowy otwarty')) {
                finishCostPerM2 = 3500;
                finishLabel = 'Adaptacja — wykończenie od surowego otwartego (~3 500 zł/m²)';
            }
            const finishCost = Math.round(finishCostPerM2 * (item.area_home || 0));

            const total = price + pcc + notaryTotal + hiddenTotal + finishCost;

            let rows = `<tr><td><strong>Koszt zakupu (cena ofertowa)</strong></td><td class="amount">${price.toLocaleString('pl-PL')} zł</td><td class="note"></td></tr>`;
            rows += `<tr><td><strong>Podatek PCC (2%)</strong></td><td class="amount">${pcc.toLocaleString('pl-PL')} zł</td><td class="note">${isPrimary ? 'Rynek pierwotny — zwolnienie' : 'Rynek wtórny'}</td></tr>`;
            rows += `<tr><td><strong>Taksa notarialna + wpis KW</strong></td><td class="amount">${notaryTotal.toLocaleString('pl-PL')} zł</td><td class="note">Wycena szacunkowa</td></tr>`;
            hiddenItems.forEach(h => {
                rows += `<tr><td><strong>${escapeHtml(h.label)}</strong></td><td class="amount">${h.val ? h.val.toLocaleString('pl-PL') + ' zł' : '?'}</td><td class="note">Koszt ukryty w opisie</td></tr>`;
            });
            if (finishCost > 0) {
                rows += `<tr><td><strong>${escapeHtml(finishLabel)}</strong></td><td class="amount">~${finishCost.toLocaleString('pl-PL')} zł</td><td class="note">Szacunek adaptacji</td></tr>`;
            }
            rows += `<tr class="total"><td>Suma nakładów kapitałowych (CAPEX)</td><td class="amount">~${total.toLocaleString('pl-PL')} zł</td><td class="note">Zakup + podatki + opłaty + adaptacja</td></tr>`;

            document.getElementById('aiBudgetBody').innerHTML = rows;
        }

        function copyAiQuestions() {
            if (!currentAiItem) return;
            const qs = currentAiItem.ai_questions || [];
            if (qs.length === 0) { showToast('Brak pytań do skopiowania.'); return; }
            const text = qs.map((q, i) => `${i + 1}. ${q}`).join('\n');
            navigator.clipboard.writeText(text).then(() => showToast('Pytania skopiowane do schowka.'));
        }

        function copyAiSms() {
            if (!currentAiItem) return;
            const item = currentAiItem;
            const title = item.title || '';
            const price = item.price ? Math.round(item.price).toLocaleString('pl-PL') + ' zł' : '';
            const sms = `Dzień dobry,\nJestem zainteresowany/a ofertą: "${title}" (${price}).\nCzy nieruchomość jest nadal dostępna? Kiedy mogę umówić się na oględziny?\nPozdrawiam`;
            navigator.clipboard.writeText(sms).then(() => showToast('Gotowa wiadomość SMS skopiowana.'));
        }

        function copyNegotiationArguments() {
            if (!currentAiItem) return;
            const args = currentAiItem.negotiation_arguments || [];
            if (args.length === 0) { showToast('Brak argumentów do skopiowania.'); return; }
            const heading = `Strategia negocjacyjna dla oferty: ${currentAiItem.title} (${currentAiItem.url})\n` +
                `Sugerowane otwarcie: ${currentAiItem.suggested_opening_offer ? Math.round(currentAiItem.suggested_opening_offer).toLocaleString('pl-PL') + ' zł' : 'b/d'}\n\n` +
                `Argumenty korygujące cenę:\n`;
            const text = heading + args.map((a, i) => `${i + 1}. ${a}`).join('\n');
            navigator.clipboard.writeText(text).then(() => showToast('Argumenty negocjacyjne skopiowane do schowka.'));
        }

        // ========================
        // Global listeners
        // ========================
        window.addEventListener('keydown', (e) => {
            const m = document.getElementById('imgModal');
            if (m && m.classList.contains('open')) {
                if (e.key === 'ArrowLeft') {
                    e.preventDefault();
                    navModalGallery(-1);
                    return;
                } else if (e.key === 'ArrowRight') {
                    e.preventDefault();
                    navModalGallery(1);
                    return;
                } else if (e.key === 'Escape') {
                    e.preventDefault();
                    closeImgModal();
                    return;
                }
            }
            const aiM = document.getElementById('aiModal');
            if (aiM && aiM.classList.contains('open') && e.key === 'Escape') {
                e.preventDefault();
                closeAiModal(null);
                return;
            }
            const cfgM = document.getElementById('configModal');
            if (cfgM && cfgM.classList.contains('open') && e.key === 'Escape') {
                e.preventDefault();
                closeConfigModal(null);
                return;
            }
            if (e.key === 'Escape') {
                closeFiltersPopover();
                closeProfileMenu();
                closeCardMenus();
            }
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                const searchInput = document.getElementById('searchInput');
                if (searchInput) {
                    searchInput.focus();
                    searchInput.select();
                }
            }
        });

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.profile-drop')) {
                closeProfileMenu();
            }
            if (!e.target.closest('.faceted-search') && !e.target.closest('#filtersPopover')) {
                closeFiltersPopover();
            }
            if (!e.target.closest('.card-action-menu')) {
                closeCardMenus();
            }
        });

        window.addEventListener('DOMContentLoaded', async () => {
            await fetchConfig();
            const curProf = allProfiles.find(p => p.id === selectedProfileId) || allProfiles[0];
            const center = curProf ? getCityCenter(curProf.city) : [50.0375, 22.0047];
            initLeafletMap(center);
            await fetchListings();
            checkActiveScrape();
        });

        setInterval(() => {
            if (!document.hidden) fetchListings();
        }, 45000);

        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && Date.now() - lastFetchAt > 10000) fetchListings();
        });
