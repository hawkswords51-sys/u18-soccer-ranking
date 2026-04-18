// 管理画面アプリケーション
class AdminApp {
    constructor() {
        this.currentPrefecture = null;
        this.editingTeamId = null;
        this.editingChampionshipIndex = null;
        this.init();
    }

    async init() {
        // データマネージャーの初期化を待つ
        await new Promise(resolve => {
            const checkData = setInterval(() => {
                if (dataManager.data) {
                    clearInterval(checkData);
                    resolve();
                }
            }, 100);
        });

        this.setupEventListeners();
        this.loadPrefectureOptions();
    }

    setupEventListeners() {
        // メニュー切り替え
        document.querySelectorAll('.admin-menu-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.switchSection(e.currentTarget.dataset.section);
            });
        });

        // 都道府県選択（チーム管理）
        document.getElementById('prefectureSelect').addEventListener('change', (e) => {
            if (e.target.value) {
                this.loadPrefectureTeams(e.target.value);
            } else {
                document.getElementById('prefectureInfo').style.display = 'none';
            }
        });

        // 都道府県選択（大会成績管理）
        document.getElementById('champPrefectureSelect').addEventListener('change', (e) => {
            if (e.target.value) {
                this.loadPrefectureChampionships(e.target.value);
            } else {
                document.getElementById('championshipInfo').style.display = 'none';
            }
        });

        // チーム追加ボタン
        document.getElementById('addTeamBtn').addEventListener('click', () => {
            this.openTeamModal();
        });

        // 大会成績追加ボタン
        document.getElementById('addChampionshipBtn').addEventListener('click', () => {
            this.openChampionshipModal();
        });

        // モーダル閉じる
        document.getElementById('closeTeamModal').addEventListener('click', () => {
            this.closeTeamModal();
        });

        document.getElementById('closeChampionshipModal').addEventListener('click', () => {
            this.closeChampionshipModal();
        });

        document.getElementById('cancelTeamBtn').addEventListener('click', () => {
            this.closeTeamModal();
        });

        document.getElementById('cancelChampionshipBtn').addEventListener('click', () => {
            this.closeChampionshipModal();
        });

        // フォーム送信
        document.getElementById('teamForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this.saveTeam();
        });

        document.getElementById('championshipForm').addEventListener('submit', (e) => {
            e.preventDefault();
            this.saveChampionship();
        });

        // データ管理
        document.getElementById('exportDataBtn').addEventListener('click', () => {
            this.exportData();
        });

        document.getElementById('importDataBtn').addEventListener('click', () => {
            document.getElementById('importFileInput').click();
        });

        document.getElementById('importFileInput').addEventListener('change', (e) => {
            this.importData(e.target.files[0]);
        });

        document.getElementById('resetDataBtn').addEventListener('click', () => {
            this.resetData();
        });

        // モーダル外クリック
        document.getElementById('teamModal').addEventListener('click', (e) => {
            if (e.target.id === 'teamModal') {
                this.closeTeamModal();
            }
        });

        document.getElementById('championshipModal').addEventListener('click', (e) => {
            if (e.target.id === 'championshipModal') {
                this.closeChampionshipModal();
            }
        });
    }

    loadPrefectureOptions() {
        const prefectures = dataManager.getAllPrefectures();
        const teamSelect = document.getElementById('prefectureSelect');
        const champSelect = document.getElementById('champPrefectureSelect');

        prefectures.forEach(pref => {
            const option1 = new Option(pref.name, pref.id);
            const option2 = new Option(pref.name, pref.id);
            teamSelect.add(option1);
            champSelect.add(option2);
        });
    }

    switchSection(sectionName) {
        // メニューボタンの切り替え
        document.querySelectorAll('.admin-menu-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        document.querySelector(`[data-section="${sectionName}"]`).classList.add('active');

        // セクションの切り替え
        document.querySelectorAll('.admin-section').forEach(section => {
            section.classList.remove('active');
        });
        document.getElementById(`${sectionName}Section`).classList.add('active');
    }

    loadPrefectureTeams(prefId) {
        this.currentPrefecture = prefId;
        const pref = dataManager.getPrefecture(prefId);

        if (!pref) return;

        document.getElementById('prefNameDisplay').textContent = pref.name;
        document.getElementById('prefRegionDisplay').textContent = pref.region || '-';
        document.getElementById('prefTeamCount').textContent = pref.teams?.length || 0;
        document.getElementById('prefectureInfo').style.display = 'block';

        this.displayTeamsList(pref.teams || []);
    }

    displayTeamsList(teams) {
        const container = document.getElementById('teamsList');

        if (teams.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-users"></i>
                    <p>まだチームが登録されていません</p>
                </div>
            `;
            return;
        }

        const sortedTeams = [...teams].sort((a, b) => a.prefectureRank - b.prefectureRank);

        const html = sortedTeams.map(team => `
            <div class="team-item">
                <div class="team-info">
                    <div class="team-name">${team.name}</div>
                    <div class="team-details">
                        <span><strong>県内順位:</strong> ${team.prefectureRank}位</span>
                        <span><strong>リーグ:</strong> ${team.league}</span>
                        <span><strong>順位:</strong> ${team.rank}位</span>
                        <span><strong>勝点:</strong> ${team.points}</span>
                    </div>
                </div>
                <div class="team-actions">
                    <button class="btn btn-primary btn-sm" onclick="adminApp.editTeam('${team.id}')">
                        <i class="fas fa-edit"></i> 編集
                    </button>
                    <button class="btn btn-danger btn-sm" onclick="adminApp.deleteTeam('${team.id}')">
                        <i class="fas fa-trash"></i> 削除
                    </button>
                </div>
            </div>
        `).join('');

        container.innerHTML = html;
    }

    loadPrefectureChampionships(prefId) {
        this.currentPrefecture = prefId;
        const championships = dataManager.getChampionshipsByPrefecture(prefId);

        document.getElementById('championshipInfo').style.display = 'block';
        this.displayChampionshipsList(championships);
    }

    displayChampionshipsList(championships) {
        const container = document.getElementById('championshipsList');

        if (championships.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-trophy"></i>
                    <p>まだ大会成績が登録されていません</p>
                </div>
            `;
            return;
        }

        const html = championships.map((champ, index) => `
            <div class="championship-item">
                <div class="championship-info">
                    <div class="championship-year">${champ.year}年</div>
                    <div class="championship-details">
                        <strong>${champ.tournament}</strong> - ${champ.team} (${champ.result})
                    </div>
                </div>
                <div class="championship-actions">
                    <button class="btn btn-danger btn-sm" onclick="adminApp.deleteChampionship(${index})">
                        <i class="fas fa-trash"></i> 削除
                    </button>
                </div>
            </div>
        `).join('');

        container.innerHTML = html;
    }

    openTeamModal(teamId = null) {
        this.editingTeamId = teamId;

        if (teamId) {
            // 編集モード
            const pref = dataManager.getPrefecture(this.currentPrefecture);
            const team = pref.teams.find(t => t.id === teamId);

            if (team) {
                document.getElementById('teamModalTitle').textContent = 'チーム編集';
                document.getElementById('teamName').value = team.name;
                document.getElementById('teamLeague').value = team.league;
                document.getElementById('teamRank').value = team.rank;
                document.getElementById('teamPrefRank').value = team.prefectureRank;
                document.getElementById('teamPoints').value = team.points;
                document.getElementById('teamPlayed').value = team.played;
                document.getElementById('teamWon').value = team.won;
                document.getElementById('teamDrawn').value = team.drawn;
                document.getElementById('teamLost').value = team.lost;
                document.getElementById('teamGoalsFor').value = team.goalsFor;
                document.getElementById('teamGoalsAgainst').value = team.goalsAgainst;
            }
        } else {
            // 新規追加モード
            document.getElementById('teamModalTitle').textContent = '新規チーム追加';
            document.getElementById('teamForm').reset();
        }

        document.getElementById('teamModal').classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    closeTeamModal() {
        document.getElementById('teamModal').classList.remove('active');
        document.body.style.overflow = 'auto';
        this.editingTeamId = null;
    }

    saveTeam() {
        const teamData = {
            name: document.getElementById('teamName').value,
            league: document.getElementById('teamLeague').value,
            rank: parseInt(document.getElementById('teamRank').value) || 0,
            prefectureRank: parseInt(document.getElementById('teamPrefRank').value),
            points: parseInt(document.getElementById('teamPoints').value) || 0,
            played: parseInt(document.getElementById('teamPlayed').value) || 0,
            won: parseInt(document.getElementById('teamWon').value) || 0,
            drawn: parseInt(document.getElementById('teamDrawn').value) || 0,
            lost: parseInt(document.getElementById('teamLost').value) || 0,
            goalsFor: parseInt(document.getElementById('teamGoalsFor').value) || 0,
            goalsAgainst: parseInt(document.getElementById('teamGoalsAgainst').value) || 0
        };

        if (this.editingTeamId) {
            // 更新
            if (dataManager.updateTeam(this.currentPrefecture, this.editingTeamId, teamData)) {
                this.showAlert('success', 'チーム情報を更新しました');
                this.loadPrefectureTeams(this.currentPrefecture);
                this.closeTeamModal();
            } else {
                this.showAlert('error', 'チーム情報の更新に失敗しました');
            }
        } else {
            // 新規追加
            if (dataManager.addTeam(this.currentPrefecture, teamData)) {
                this.showAlert('success', 'チームを追加しました');
                this.loadPrefectureTeams(this.currentPrefecture);
                this.closeTeamModal();
            } else {
                this.showAlert('error', 'チームの追加に失敗しました');
            }
        }
    }

    editTeam(teamId) {
        this.openTeamModal(teamId);
    }

    deleteTeam(teamId) {
        if (confirm('このチームを削除してもよろしいですか?')) {
            if (dataManager.deleteTeam(this.currentPrefecture, teamId)) {
                this.showAlert('success', 'チームを削除しました');
                this.loadPrefectureTeams(this.currentPrefecture);
            } else {
                this.showAlert('error', 'チームの削除に失敗しました');
            }
        }
    }

    openChampionshipModal() {
        document.getElementById('championshipForm').reset();
        document.getElementById('champYear').value = new Date().getFullYear();
        document.getElementById('championshipModal').classList.add('active');
        document.body.style.overflow = 'hidden';
    }

    closeChampionshipModal() {
        document.getElementById('championshipModal').classList.remove('active');
        document.body.style.overflow = 'auto';
    }

    saveChampionship() {
        const champData = {
            year: parseInt(document.getElementById('champYear').value),
            tournament: document.getElementById('champTournament').value,
            team: document.getElementById('champTeam').value,
            result: document.getElementById('champResult').value
        };

        if (dataManager.addChampionship(this.currentPrefecture, champData)) {
            this.showAlert('success', '大会成績を追加しました');
            this.loadPrefectureChampionships(this.currentPrefecture);
            this.closeChampionshipModal();
        } else {
            this.showAlert('error', '大会成績の追加に失敗しました');
        }
    }

    deleteChampionship(index) {
        if (confirm('この大会成績を削除してもよろしいですか?')) {
            if (dataManager.deleteChampionship(this.currentPrefecture, index)) {
                this.showAlert('success', '大会成績を削除しました');
                this.loadPrefectureChampionships(this.currentPrefecture);
            } else {
                this.showAlert('error', '大会成績の削除に失敗しました');
            }
        }
    }

    exportData() {
        const dataStr = dataManager.exportData();
        const blob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `soccer-data-${new Date().toISOString().split('T')[0]}.json`;
        link.click();
        URL.revokeObjectURL(url);

        this.showAlert('success', 'データをエクスポートしました');
    }

    async importData(file) {
        if (!file) return;

        try {
            const text = await file.text();
            if (dataManager.importData(text)) {
                this.showAlert('success', 'データをインポートしました');
                // ページをリロード
                setTimeout(() => {
                    location.reload();
                }, 1500);
            } else {
                this.showAlert('error', 'データのインポートに失敗しました。ファイル形式を確認してください。');
            }
        } catch (error) {
            this.showAlert('error', 'ファイルの読み込みに失敗しました');
        }
    }

    async resetData() {
        if (confirm('データをデフォルトに戻しますか？\n現在のデータは失われます。')) {
            await dataManager.resetToDefault();
            this.showAlert('success', 'データをデフォルトに戻しました');
            setTimeout(() => {
                location.reload();
            }, 1500);
        }
    }

    showAlert(type, message) {
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type}`;
        
        const icon = type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle';
        alertDiv.innerHTML = `
            <i class="fas fa-${icon}"></i>
            <span>${message}</span>
        `;

        const container = document.querySelector('.admin-card');
        container.insertBefore(alertDiv, container.firstChild);

        setTimeout(() => {
            alertDiv.remove();
        }, 3000);
    }
}

// アプリケーションの初期化
let adminApp;
window.addEventListener('DOMContentLoaded', () => {
    adminApp = new AdminApp();
});
