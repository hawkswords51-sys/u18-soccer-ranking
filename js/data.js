// データ管理クラス
class DataManager {
    constructor() {
        this.data = null;
        this.init();
    }

    async init() {
        // 常にJSONファイルから最新データを読み込む
        await this.loadFromFile();

        // ローカルストレージにカスタム編集データがある場合はマージ
        const customData = localStorage.getItem('soccerTeamsCustomData');
        // ※ 自動更新後はキャッシュを使わないよう、JSONロード後はlocalStorageを上書き
        if (customData) {
            try {
                const custom = JSON.parse(customData);
                // カスタムデータを優先的にマージ
                this.data = { ...this.data, ...custom };
            } catch (error) {
                console.error('カスタムデータの読み込みに失敗:', error);
            }
        }

        // 初期化完了イベントを発火（最終更新バナーなどに使用）
        window.dataManager = this;
        window.dispatchEvent(new Event('dataManagerReady'));
    }

    async loadFromFile() {
        try {
            // キャッシュを回避して常に最新データを取得
            const response = await fetch('data/teams.json?_=' + Date.now());
            const rawData = await response.json();

            // _meta フィールド（スクレイパーが書き込む）を保持
            this._meta = rawData._meta || null;

            // 実在チーム名ジェネレーターで10チームに拡張
            if (window.realTeamsGenerator) {
                this.data = {};
                Object.entries(rawData).forEach(([prefId, prefData]) => {
                    if (prefId === '_meta') return; // メタデータはスキップ
                    this.data[prefId] = {
                        ...prefData,
                        teams: window.realTeamsGenerator.generateRealTeamsForPrefecture(
                            prefId,
                            prefData.name,
                            prefData.teams || []
                        )
                    };
                });
                console.log('実在チームデータを10チームに拡張しました');
            } else {
                this.data = {};
                Object.entries(rawData).forEach(([prefId, prefData]) => {
                    if (prefId === '_meta') return;
                    this.data[prefId] = prefData;
                });
                console.log('実在チームデータを読み込みました');
            }

            this.saveToLocalStorage();
        } catch (error) {
            console.error('データの読み込みに失敗しました:', error);
            this.data = {};
        }
    }

    saveToLocalStorage() {
        // カスタム編集データとして保存（JSONファイルは上書きしない）
        localStorage.setItem('soccerTeamsCustomData', JSON.stringify(this.data));
    }

    /** スクレイパーが書き込んだ最終更新情報を返す */
    getLastUpdated() {
        return this._meta || null;
    }

    getAllPrefectures() {
        return Object.keys(this.data).map(key => ({
            id: key,
            ...this.data[key]
        }));
    }

    getPrefecture(prefId) {
        return this.data[prefId] || null;
    }

    getTeamsByPrefecture(prefId) {
        const pref = this.getPrefecture(prefId);
        return pref ? pref.teams : [];
    }

    getChampionshipsByPrefecture(prefId) {
        const pref = this.getPrefecture(prefId);
        return pref ? pref.championships || [] : [];
    }

    searchTeams(query) {
        const results = [];
        const lowerQuery = query.toLowerCase();

        Object.keys(this.data).forEach(prefId => {
            const pref = this.data[prefId];
            pref.teams.forEach(team => {
                if (team.name.toLowerCase().includes(lowerQuery)) {
                    results.push({
                        ...team,
                        prefectureId: prefId,
                        prefectureName: pref.name
                    });
                }
            });
        });

        return results;
    }

    getHighestLeagueLevel(prefId) {
        const teams = this.getTeamsByPrefecture(prefId);
        if (teams.length === 0) return 'no-data';

        const hasPremiér = teams.some(t => t.league.includes('プレミアリーグ'));
        const hasPrince = teams.some(t => t.league.includes('プリンスリーグ'));

        if (hasPremiér) return 'premier';
        if (hasPrince) return 'prince';
        return 'prefecture';
    }

    updatePrefecture(prefId, data) {
        if (!this.data[prefId]) {
            this.data[prefId] = {
                name: data.name,
                region: data.region,
                teams: [],
                championships: []
            };
        }
        
        Object.assign(this.data[prefId], data);
        this.saveToLocalStorage();
    }

    addTeam(prefId, team) {
        if (!this.data[prefId]) {
            return false;
        }

        if (!team.id) {
            team.id = this.generateTeamId(prefId);
        }

        this.data[prefId].teams.push(team);
        this.saveToLocalStorage();
        return true;
    }

    updateTeam(prefId, teamId, updatedTeam) {
        if (!this.data[prefId]) return false;

        const teamIndex = this.data[prefId].teams.findIndex(t => t.id === teamId);
        if (teamIndex === -1) return false;

        this.data[prefId].teams[teamIndex] = {
            ...this.data[prefId].teams[teamIndex],
            ...updatedTeam
        };

        this.saveToLocalStorage();
        return true;
    }

    deleteTeam(prefId, teamId) {
        if (!this.data[prefId]) return false;

        const teamIndex = this.data[prefId].teams.findIndex(t => t.id === teamId);
        if (teamIndex === -1) return false;

        this.data[prefId].teams.splice(teamIndex, 1);
        this.saveToLocalStorage();
        return true;
    }

    addChampionship(prefId, championship) {
        if (!this.data[prefId]) return false;

        if (!this.data[prefId].championships) {
            this.data[prefId].championships = [];
        }

        this.data[prefId].championships.push(championship);
        this.saveToLocalStorage();
        return true;
    }

    deleteChampionship(prefId, index) {
        if (!this.data[prefId] || !this.data[prefId].championships) return false;

        this.data[prefId].championships.splice(index, 1);
        this.saveToLocalStorage();
        return true;
    }

    generateTeamId(prefId) {
        const prefix = prefId.substring(0, 1);
        const timestamp = Date.now().toString(36);
        const random = Math.random().toString(36).substring(2, 5);
        return `${prefix}${timestamp}${random}`;
    }

    exportData() {
        return JSON.stringify(this.data, null, 2);
    }

    importData(jsonString) {
        try {
            const newData = JSON.parse(jsonString);
            this.data = newData;
            this.saveToLocalStorage();
            return true;
        } catch (error) {
            console.error('データのインポートに失敗しました:', error);
            return false;
        }
    }

    resetToDefault() {
        localStorage.removeItem('soccerTeamsCustomData');
        return this.loadFromFile();
    }
}

// グローバルインスタンス
const dataManager = new DataManager();
