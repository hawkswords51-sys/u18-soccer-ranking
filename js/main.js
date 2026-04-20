// メインアプリケーション
class SoccerApp {
    constructor() {
        this.map = null;
        this.currentPrefecture = null;
        this.init();
    }

    async init() {
        console.log('SoccerApp initialization started');

        // 地域別リストの初期化
        this.map = new RegionListGenerator('japanMap');
        await this.map.generate();
        console.log('Region list generated');

        // イベントリスナーの設定
        this.setupEventListeners();
        console.log('Event listeners setup completed');

        // 検索機能の初期化
        this.setupSearch();
        console.log('Search functionality initialized');
    }

    setupEventListeners() {
        // 都道府県選択イベント
        document.addEventListener('prefectureSelected', (e) => {
            console.log('prefectureSelected event received in main.js:', e.detail);
            this.showPrefectureDetail(e.detail.prefId, e.detail.prefName);
        });

        // モーダル閉じるボタン
        document.getElementById('closeModal').addEventListener('click', () => {
            this.closeModal();
        });

        // モーダル外クリック
        document.getElementById('detailModal').addEventListener('click', (e) => {
            if (e.target.id === 'detailModal') {
                this.closeModal();
            }
        });

        // タブ切り替え
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.switchTab(e.target.dataset.tab);
            });
        });

        // ホームボタン
        document.getElementById('homeBtn').addEventListener('click', (e) => {
            e.preventDefault();
            this.showHome();
        });

        // 検索ボタン
        document.getElementById('searchBtn').addEventListener('click', (e) => {
            e.preventDefault();
            this.toggleSearch();
        });

        // ESCキーでモーダルを閉じる
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeModal();
            }
        });

        // 情報カードのクリックでリーグ順位表を表示
        document.querySelectorAll('.info-card').forEach(card => {
            const iconDiv = card.querySelector('.info-icon');
            if (!iconDiv) return;
            if (iconDiv.classList.contains('premier')) {
                card.style.cursor = 'pointer';
                card.setAttribute('title', 'クリックしてプレミアリーグの順位表を表示');
                card.addEventListener('click', () => this.showLeagueGroup('premier'));
            } else if (iconDiv.classList.contains('prince')) {
                card.style.cursor = 'pointer';
                card.setAttribute('title', 'クリックしてプリンスリーグの順位表を表示');
                card.addEventListener('click', () => this.showLeagueGroup('prince'));
            }
        });
    }

    setupSearch() {
        const searchInput = document.getElementById('searchInput');
        const clearBtn = document.getElementById('clearSearchBtn');

        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.trim();

            if (query) {
                clearBtn.style.display = 'block';
                this.performSearch(query);
            } else {
                clearBtn.style.display = 'none';
                this.clearSearchResults();
            }
        });

        clearBtn.addEventListener('click', () => {
            searchInput.value = '';
            clearBtn.style.display = 'none';
            this.clearSearchResults();
            searchInput.focus();
        });
    }

    performSearch(query) {
        const results = dataManager.searchTeams(query);
        this.displaySearchResults(results);
    }

    displaySearchResults(results) {
        const container = document.getElementById('searchResults');

        if (results.length === 0) {
            container.innerHTML = `
                <div class="search-no-results">
                    <i class="fas fa-search"></i>
                    <p>該当するチームが見つかりませんでした</p>
                </div>
            `;
            return;
        }

        const html = results.map(team => `
            <div class="search-result-item" data-pref-id="${team.prefectureId}">
                <div class="search-result-team">${team.name}</div>
                <div class="search-result-info">
                    <span><i class="fas fa-map-marker-alt"></i> ${team.prefectureName}</span>
                    <span><i class="fas fa-trophy"></i> ${team.league}</span>
                    <span><i class="fas fa-sort-numeric-down"></i> 順位: ${team.rank}位</span>
                </div>
            </div>
        `).join('');

        container.innerHTML = html;

        // 検索結果のクリックイベント
        container.querySelectorAll('.search-result-item').forEach(item => {
            item.addEventListener('click', () => {
                const prefId = item.dataset.prefId;
                const pref = dataManager.getPrefecture(prefId);
                if (pref) {
                    this.showPrefectureDetail(prefId, pref.name);
                    this.showHome(); // 検索画面を閉じる
                }
            });
        });
    }

    clearSearchResults() {
        document.getElementById('searchResults').innerHTML = '';
    }

    toggleSearch() {
        const searchSection = document.getElementById('searchSection');
        const mapSection = document.getElementById('mapSection');

        if (searchSection.style.display === 'none') {
            searchSection.style.display = 'block';
            mapSection.style.display = 'none';
            document.getElementById('searchInput').focus();
        } else {
            searchSection.style.display = 'none';
            mapSection.style.display = 'block';
        }
    }

    showHome() {
        document.getElementById('searchSection').style.display = 'none';
        document.getElementById('mapSection').style.display = 'block';
        document.getElementById('searchInput').value = '';
        document.getElementById('clearSearchBtn').style.display = 'none';
        this.clearSearchResults();
    }

    showPrefectureDetail(prefId, prefName) {
        this.currentPrefecture = prefId;
        const pref = dataManager.getPrefecture(prefId);

        console.log('Prefecture ID:', prefId);
        console.log('Prefecture Data:', pref);

        if (!pref || !pref.teams || pref.teams.length === 0) {
            alert(`この都道府県（${prefName}）のデータはまだ登録されていません。\nID: ${prefId}`);
            return;
        }

        // 都道府県詳細用のUIを復元（リーグ表示から戻ってきた場合のため）
        const statsSummary = document.querySelector('.stats-summary');
        const tabsEl = document.querySelector('.tabs');
        if (statsSummary) statsSummary.style.display = '';
        if (tabsEl) tabsEl.style.display = '';

        // モーダルタイトル
        document.getElementById('modalTitle').innerHTML = `
            <i class="fas fa-map-marker-alt"></i> ${prefName}
        `;

        // 統計情報
        document.getElementById('teamCount').textContent = pref.teams.length;
        document.getElementById('topLeague').textContent = this.getTopLeagueName(pref.teams);

        // リーグ戦テーブル
        this.displayTeamsTable(pref.teams);

        // 大会成績テーブル
        this.displayChampionshipsTable(pref.championships || []);

        // リーグタブをアクティブに戻す
        this.switchTab('league');

        // モーダルを表示
        this.openModal();
    }

    getTopLeagueName(teams) {
        const hasPremiér = teams.some(t => t.league.includes('プレミアリーグ'));
        const hasPrince = teams.some(t => t.league.includes('プリンスリーグ'));

        if (hasPremiér) return 'プレミアリーグ';
        if (hasPrince) return 'プリンスリーグ';
        return '都道府県リーグ';
    }

    leagueTierPriority(league) {
        if (league.includes('プレミアリーグ')) return 0;
        if (league.includes('プリンスリーグ')) {
            if (league.includes('2部')) return 2;
            return 1;
        }
        return 3;
    }

    displayTeamsTable(teams) {
        const container = document.getElementById('teamsTable');

        const sortedTeams = [...teams].sort((a, b) => {
            const tierDiff = this.leagueTierPriority(a.league) - this.leagueTierPriority(b.league);
            if (tierDiff !== 0) return tierDiff;
            return a.rank - b.rank;
        });

        const html = `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>県内順位</th>
                        <th>チーム名</th>
                        <th>リーグ</th>
                        <th>順位</th>
                        <th>勝点</th>
                        <th>試合数</th>
                        <th>勝</th>
                        <th>分</th>
                        <th>負</th>
                        <th>得点</th>
                        <th>失点</th>
                        <th>得失差</th>
                    </tr>
                </thead>
                <tbody>
                    ${sortedTeams.map((team, index) => this.createTeamRow(team, index + 1)).join('')}
                </tbody>
            </table>
        `;

        container.innerHTML = html;
    }

    createTeamRow(team, prefRank) {
        const goalDiff = team.goalsFor - team.goalsAgainst;
        const rankClass = prefRank <= 3 ? `rank-${prefRank}` : 'rank-other';

        let leagueBadgeClass = 'prefecture';
        if (team.league.includes('プレミアリーグ')) {
            leagueBadgeClass = 'premier';
        } else if (team.league.includes('プリンスリーグ')) {
            leagueBadgeClass = 'prince';
        }

        return `
            <tr>
                <td>
                    <span class="rank-badge ${rankClass}">${prefRank}</span>
                </td>
                <td><strong>${team.name}</strong></td>
                <td>
                    <span class="league-badge ${leagueBadgeClass}">${team.league}</span>
                </td>
                <td>${team.rank}位</td>
                <td><strong>${team.points}</strong></td>
                <td>${team.played}</td>
                <td>${team.won}</td>
                <td>${team.drawn}</td>
                <td>${team.lost}</td>
                <td>${team.goalsFor}</td>
                <td>${team.goalsAgainst}</td>
                <td style="color: ${goalDiff > 0 ? '#28a745' : goalDiff < 0 ? '#dc3545' : '#666'}">
                    ${goalDiff > 0 ? '+' : ''}${goalDiff}
                </td>
            </tr>
        `;
    }

    displayChampionshipsTable(championships) {
        const container = document.getElementById('championshipsTable');

        if (championships.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 40px; color: #666;">
                    <i class="fas fa-trophy" style="font-size: 3rem; opacity: 0.3; margin-bottom: 15px;"></i>
                    <p>大会成績データがありません</p>
                </div>
            `;
            return;
        }

        const html = `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>年度</th>
                        <th>大会名</th>
                        <th>出場チーム</th>
                        <th>成績</th>
                    </tr>
                </thead>
                <tbody>
                    ${championships.map(c => `
                        <tr>
                            <td>${c.year}年</td>
                            <td>${c.tournament}</td>
                            <td><strong>${c.team}</strong></td>
                            <td>${c.result}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;

        container.innerHTML = html;
    }

    switchTab(tabName) {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        const targetBtn = document.querySelector(`[data-tab="${tabName}"]`);
        if (targetBtn) targetBtn.classList.add('active');

        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
        });
        const targetContent = document.getElementById(`${tabName}Tab`);
        if (targetContent) targetContent.classList.add('active');
    }

    openModal() {
        const modal = document.getElementById('detailModal');
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    closeModal() {
        const modal = document.getElementById('detailModal');
        modal.classList.remove('active');
        document.body.style.overflow = 'auto';
    }

    // ============================================================
    // プレミアリーグ / プリンスリーグ 全体順位表の表示
    // ============================================================

    async showLeagueGroup(type) {
        const keyword = type === 'premier' ? 'プレミアリーグ' : 'プリンスリーグ';
        const title = type === 'premier' ? 'プレミアリーグ' : 'プリンスリーグ';
        const icon = type === 'premier' ? 'trophy' : 'medal';

        // realTeamsGeneratorが league 情報を上書きするため、
        // teams.json を直接読み込んで生データから対象リーグを抽出する
        let rawData = null;
        try {
            const response = await fetch('data/teams.json?_=' + Date.now());
            rawData = await response.json();
        } catch (e) {
            console.error('teams.json の読み込みに失敗:', e);
        }

        const allTeams = [];
        if (rawData) {
            Object.entries(rawData).forEach(([prefId, prefData]) => {
                if (prefId === '_meta') return;
                if (!prefData || !Array.isArray(prefData.teams)) return;
                prefData.teams.forEach(team => {
                    if (team.league && team.league.includes(keyword)) {
                        allTeams.push({
                            ...team,
                            prefectureId: prefId,
                            prefectureName: prefData.name
                        });
                    }
                });
            });
        }

        if (allTeams.length === 0) {
            alert(`${title}のデータがまだ登録されていません。\n自動更新を実行してからお試しください。`);
            return;
        }

        // リーグ名でグルーピング
        const groups = {};
        allTeams.forEach(team => {
            const key = team.league;
            if (!groups[key]) groups[key] = [];
            groups[key].push(team);
        });

        Object.values(groups).forEach(teams => {
            // リーグ表示では leagueRank（プリンス/プレミア等のリーグ内順位）を優先し、
            // 無い場合は従来の rank（都道府県順位）にフォールバック
            teams.sort((a, b) => (a.leagueRank || a.rank || 99) - (b.leagueRank || b.rank || 99));
        });

        const sortedKeys = Object.keys(groups).sort((a, b) =>
            this.leagueGroupSortOrder(type, a) - this.leagueGroupSortOrder(type, b)
        );

        this.currentPrefecture = null;
        document.getElementById('modalTitle').innerHTML = `
            <i class="fas fa-${icon}"></i> ${title} 順位表
        `;

        const statsSummary = document.querySelector('.stats-summary');
        const tabsEl = document.querySelector('.tabs');
        if (statsSummary) statsSummary.style.display = 'none';
        if (tabsEl) tabsEl.style.display = 'none';

        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        const leagueTab = document.getElementById('leagueTab');
        if (leagueTab) leagueTab.classList.add('active');

        const container = document.getElementById('teamsTable');
        container.innerHTML = sortedKeys.map(key =>
            this.renderLeagueTable(key, groups[key])
        ).join('');

        const champContainer = document.getElementById('championshipsTable');
        if (champContainer) champContainer.innerHTML = '';

        this.openModal();
    }

    leagueGroupSortOrder(type, leagueName) {
        if (type === 'premier') {
            if (leagueName.includes('EAST')) return 1;
            if (leagueName.includes('WEST')) return 2;
            return 99;
        }
        const regions = ['北海道', '東北', '関東', '北信越', '東海', '関西', '中国', '四国', '九州'];
        let score = 1000;
        for (let i = 0; i < regions.length; i++) {
            if (leagueName.includes(regions[i])) {
                score = (i + 1) * 10;
                break;
            }
        }
        if (leagueName.includes('2部')) score += 2;
        else if (leagueName.includes('1部')) score += 1;
        return score;
    }

    renderLeagueTable(leagueName, teams) {
        const prefectureHeader = teams.some(t => t.prefectureName) ? '<th>所属</th>' : '';

        return `
            <div class="league-group-block" style="margin-top:24px;">
                <h3 style="margin:24px 0 12px; padding:8px 12px; background:#f2f5fb; border-left:4px solid #1e3a8a; color:#1e3a8a; font-size:1.1rem;">
                    <i class="fas fa-flag"></i>
                    ${this.escapeHtml(leagueName)}
                    <span style="float:right; color:#666; font-weight:normal; font-size:0.9rem;">${teams.length}チーム</span>
                </h3>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>順位</th>
                            <th>チーム名</th>
                            ${prefectureHeader}
                            <th>勝点</th>
                            <th>試合</th>
                            <th>勝</th>
                            <th>分</th>
                            <th>負</th>
                            <th>得点</th>
                            <th>失点</th>
                            <th>得失差</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${teams.map(t => this.createLeagueTeamRow(t, !!prefectureHeader)).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    createLeagueTeamRow(team, showPrefecture) {
        const goalsFor = team.goalsFor ?? 0;
        const goalsAgainst = team.goalsAgainst ?? 0;
        const goalDiff = goalsFor - goalsAgainst;
        // リーグ画面では leagueRank（リーグ内順位）を使用。
        // leagueRank が無いチームは従来通り都道府県順位（rank）にフォールバック。
        const rank = team.leagueRank || team.rank || '-';
        const rankClass = (typeof rank === 'number' && rank <= 3) ? `rank-${rank}` : 'rank-other';

        return `
            <tr>
                <td><span class="rank-badge ${rankClass}">${rank}</span></td>
                <td><strong>${this.escapeHtml(team.name)}</strong></td>
                ${showPrefecture ? `<td>${this.escapeHtml(team.prefectureName || '-')}</td>` : ''}
                <td><strong>${team.points ?? 0}</strong></td>
                <td>${team.played ?? 0}</td>
                <td>${team.won ?? 0}</td>
                <td>${team.drawn ?? 0}</td>
                <td>${team.lost ?? 0}</td>
                <td>${goalsFor}</td>
                <td>${goalsAgainst}</td>
                <td style="color: ${goalDiff > 0 ? '#28a745' : goalDiff < 0 ? '#dc3545' : '#666'}">
                    ${goalDiff > 0 ? '+' : ''}${goalDiff}
                </td>
            </tr>
        `;
    }

    escapeHtml(str) {
        if (str == null) return '';
        return String(str).replace(/[&<>"']/g, c => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[c]));
    }
}

// アプリケーションの初期化
let app;
window.addEventListener('DOMContentLoaded', () => {
    app = new SoccerApp();
});
