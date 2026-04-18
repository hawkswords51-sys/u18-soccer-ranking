// 日本地図の都道府県データ（簡易版SVGパス）
const prefecturesData = {
    hokkaido: { name: '北海道', path: 'M250,10 L280,15 L290,30 L285,50 L270,60 L250,55 L240,40 L245,25 Z' },
    aomori: { name: '青森県', path: 'M260,75 L275,70 L280,85 L270,95 L255,90 Z' },
    iwate: { name: '岩手県', path: 'M270,100 L280,95 L285,115 L275,125 L265,120 Z' },
    miyagi: { name: '宮城県', path: 'M265,130 L275,128 L278,140 L268,145 Z' },
    akita: { name: '秋田県', path: 'M255,100 L265,98 L268,118 L258,120 Z' },
    yamagata: { name: '山形県', path: 'M258,125 L268,123 L270,138 L260,140 Z' },
    fukushima: { name: '福島県', path: 'M260,145 L273,143 L275,160 L263,162 Z' },
    ibaraki: { name: '茨城県', path: 'M275,165 L283,163 L285,178 L277,180 Z' },
    tochigi: { name: '栃木県', path: 'M268,163 L276,161 L278,173 L270,175 Z' },
    gunma: { name: '群馬県', path: 'M260,163 L268,161 L270,173 L262,175 Z' },
    saitama: { name: '埼玉県', path: 'M265,178 L273,176 L275,188 L267,190 Z' },
    chiba: { name: '千葉県', path: 'M278,180 L288,178 L292,193 L282,195 Z' },
    tokyo: { name: '東京都', path: 'M270,185 L278,183 L280,193 L272,195 Z' },
    kanagawa: { name: '神奈川県', path: 'M265,193 L275,191 L277,201 L267,203 Z' },
    niigata: { name: '新潟県', path: 'M245,135 L258,133 L260,155 L247,157 Z' },
    toyama: { name: '富山県', path: 'M238,155 L248,153 L250,165 L240,167 Z' },
    ishikawa: { name: '石川県', path: 'M230,150 L240,148 L242,163 L232,165 Z' },
    fukui: { name: '福井県', path: 'M235,165 L245,163 L247,178 L237,180 Z' },
    yamanashi: { name: '山梨県', path: 'M255,178 L265,176 L267,188 L257,190 Z' },
    nagano: { name: '長野県', path: 'M245,163 L258,161 L260,183 L247,185 Z' },
    gifu: { name: '岐阜県', path: 'M240,175 L252,173 L254,188 L242,190 Z' },
    shizuoka: { name: '静岡県', path: 'M250,193 L265,191 L267,208 L252,210 Z' },
    aichi: { name: '愛知県', path: 'M240,193 L252,191 L254,205 L242,207 Z' },
    mie: { name: '三重県', path: 'M245,208 L255,206 L257,220 L247,222 Z' },
    shiga: { name: '滋賀県', path: 'M235,195 L245,193 L247,205 L237,207 Z' },
    kyoto: { name: '京都府', path: 'M230,203 L240,201 L242,213 L232,215 Z' },
    osaka: { name: '大阪府', path: 'M235,210 L243,208 L245,218 L237,220 Z' },
    hyogo: { name: '兵庫県', path: 'M220,205 L233,203 L235,220 L222,222 Z' },
    nara: { name: '奈良県', path: 'M238,215 L246,213 L248,225 L240,227 Z' },
    wakayama: { name: '和歌山県', path: 'M238,225 L248,223 L250,238 L240,240 Z' },
    tottori: { name: '鳥取県', path: 'M210,208 L222,206 L224,218 L212,220 Z' },
    shimane: { name: '島根県', path: 'M195,210 L210,208 L212,225 L197,227 Z' },
    okayama: { name: '岡山県', path: 'M215,218 L227,216 L229,230 L217,232 Z' },
    hiroshima: { name: '広島県', path: 'M200,220 L215,218 L217,235 L202,237 Z' },
    yamaguchi: { name: '山口県', path: 'M185,225 L200,223 L202,240 L187,242 Z' },
    tokushima: { name: '徳島県', path: 'M235,233 L245,231 L247,243 L237,245 Z' },
    kagawa: { name: '香川県', path: 'M225,230 L235,228 L237,240 L227,242 Z' },
    ehime: { name: '愛媛県', path: 'M210,233 L223,231 L225,248 L212,250 Z' },
    kochi: { name: '高知県', path: 'M220,245 L235,243 L237,260 L222,262 Z' },
    fukuoka: { name: '福岡県', path: 'M170,235 L183,233 L185,248 L172,250 Z' },
    saga: { name: '佐賀県', path: 'M165,245 L175,243 L177,255 L167,257 Z' },
    nagasaki: { name: '長崎県', path: 'M155,243 L168,241 L170,258 L157,260 Z' },
    kumamoto: { name: '熊本県', path: 'M170,250 L183,248 L185,268 L172,270 Z' },
    oita: { name: '大分県', path: 'M185,245 L198,243 L200,260 L187,262 Z' },
    miyazaki: { name: '宮崎県', path: 'M185,265 L195,263 L197,283 L187,285 Z' },
    kagoshima: { name: '鹿児島県', path: 'M170,275 L185,273 L187,295 L172,297 Z' },
    okinawa: { name: '沖縄県', path: 'M140,310 L155,308 L157,320 L142,322 Z' }
};

// 地図生成クラス
class JapanMapGenerator {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.svg = null;
    }

    async generate() {
        // データマネージャーの初期化を待つ
        await new Promise(resolve => {
            const checkData = setInterval(() => {
                if (dataManager.data) {
                    clearInterval(checkData);
                    resolve();
                }
            }, 100);
        });

        console.log('Map generation started');
        console.log('Available prefectures in data:', Object.keys(dataManager.data));
        
        this.createSVG();
        this.drawPrefectures();
        
        console.log('Map generation completed');
    }

    createSVG() {
        this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        this.svg.setAttribute('viewBox', '0 0 350 350');
        this.svg.setAttribute('width', '100%');
        this.svg.setAttribute('height', 'auto');
        this.svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        this.svg.style.minHeight = '500px';
        this.container.appendChild(this.svg);
    }

    drawPrefectures() {
        Object.keys(prefecturesData).forEach(prefId => {
            const prefData = prefecturesData[prefId];
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            
            path.setAttribute('d', prefData.path);
            path.setAttribute('class', 'prefecture');
            path.setAttribute('data-pref-id', prefId);
            path.setAttribute('data-pref-name', prefData.name);

            // リーグレベルに応じた色分け
            const leagueLevel = dataManager.getHighestLeagueLevel(prefId);
            path.classList.add(`has-${leagueLevel}`);

            console.log(`Prefecture: ${prefId} (${prefData.name}) - Level: ${leagueLevel}`);

            // ツールチップ
            const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
            title.textContent = prefData.name;
            path.appendChild(title);

            // クリックイベント
            path.addEventListener('click', () => {
                console.log(`Clicked: ${prefId} (${prefData.name})`);
                this.onPrefectureClick(prefId, prefData.name);
            });

            this.svg.appendChild(path);
        });
    }

    onPrefectureClick(prefId, prefName) {
        // モーダル表示イベントを発火
        const event = new CustomEvent('prefectureSelected', {
            detail: { prefId, prefName }
        });
        document.dispatchEvent(event);
    }

    updateColors() {
        const paths = this.svg.querySelectorAll('.prefecture');
        paths.forEach(path => {
            const prefId = path.getAttribute('data-pref-id');
            const leagueLevel = dataManager.getHighestLeagueLevel(prefId);
            
            // 既存のクラスを削除
            path.classList.remove('has-premier', 'has-prince', 'has-prefecture', 'no-data');
            
            // 新しいクラスを追加
            path.classList.add(`has-${leagueLevel}`);
        });
    }
}
