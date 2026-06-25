# High-Winrate Entry Plan Upgrade

Cap nhat: 2026-06-21.

Muc tieu cua thay doi nay la tang ti le thang paper bot theo huong thuc dung: loc bot lenh nhieu hon, bao ve lenh dang dung huong som hon, va tranh toi uu qua muc. Muc tieu 80% win rate khong duoc xem la bao dam loi nhuan; no chi co y nghia khi di kem profit factor, drawdown, phi, slippage va mau giao dich du lon.

## Nguon tham khao

- Freqtrade stoploss docs: static stop, trailing stop, stoploss on exchange, va canh bao stop qua chat co the khong khop trong bien dong manh.
- Freqtrade hyperopt docs: dung toi uu tham so bang Optuna thay vi chon nguong theo cam tinh.
- Freqtrade lookahead-analysis docs: tranh backtest "nhin tuong lai"; nhung chien luoc qua dep thuong do bias.
- Jesse entering/exiting docs: entry chi la yes/no; sau do phai dinh nghia entry, stop-loss, take-profit ro rang. Jesse cung ho tro chia TP nhieu diem va dynamic update position.
- Jesse optimization, Monte Carlo, rule significance docs: toi uu theo risk-adjusted return, kiem tra overfitting, va test xem rule vao lenh co edge that hay chi la may man.
- Hummingbot framework docs: nen tach signal engine va execution engine, dac biet neu sau nay chuyen tu paper sang live.

## So sanh voi plan hien tai

Plan hien tai co diem tot:

- Da co multi-confirmation gate, khong vao lenh chi vi mot tin hieu whale/smart-money.
- Da co cost guard tinh fee, slippage va gas.
- Da co paper broker va learner ghi nhan ket qua.

Diem can nang cap:

- Entry threshold con hoi de doi voi muc tieu win-rate cao.
- SHORT co the bi mo khi top-trader ratio van nghieng long, neu cac thanh phan khac keo score am.
- Exit logic truoc day qua tinh: vao lenh xong chi cho stop hoac TP co dinh.
- Chua co breakeven/trailing stop, nen lenh dang dung huong co the quay lai thanh lo.
- Chua co quy trinh significance/Monte Carlo/walk-forward nen khong nen tin learner khi mau con mong.

## Thay doi da lam

1. Tang precision cua Strategy Gate:
   - Tang nguong candidate score/confidence.
   - Them nguong high-precision score/confidence truoc khi gate pass.
   - Chan lenh neu co qua nhieu confirmation nguoc chieu.
   - LONG can tape pressure ro hon.
   - SHORT can sell tape ro hon.
   - Chan SHORT khi top trader positioning con qua long ma derivatives chua that su bearish.
   - Chan LONG khi crowd long qua dong nhung derivatives edge khong ung ho.

2. Them dynamic exit:
   - Khi loi nhuan dat `breakeven_trigger_r`, stop duoc keo ve gan hoa von.
   - Khi loi nhuan dat `trailing_trigger_r`, stop bat dau trail theo gia.
   - Mac dinh moi:
     - `breakeven_trigger_r = 0.9`
     - `breakeven_lock_r = 0.05`
     - `trailing_trigger_r = 1.4`
     - `trailing_distance_r = 0.75`

3. Them config runtime:
   - Cac tham so breakeven/trailing da co trong `config.example.toml`, `PaperConfig`, va web API overrides.

## Huong tiep theo de tien toi 80% win rate

Khong nen toi uu truc tiep "win rate" mot minh. Nen toi uu theo bo dieu kien:

- win rate >= 65-80%
- profit factor > 1.3
- max drawdown chap nhan duoc
- so lenh du lon, it nhat 200-500 lenh moi symbol
- ket qua on dinh tren BTC, ETH, SOL rieng biet
- walk-forward out-of-sample khong sap
- Monte Carlo khong cho thay equity curve qua may man

De tang win rate thuc te, thu tu uu tien:

1. Them multi-timeframe gate: 1m entry chi duoc LONG neu 5m/15m khong bearish manh, SHORT neu 5m/15m khong bullish manh.
2. Them partial take-profit: chot 50% o 1R, phan con lai trailing.
3. Them cooldown sau stop-loss rieng theo symbol.
4. Tach threshold theo symbol: BTC/ETH/SOL co hanh vi khac nhau.
5. Them significance test cho tung rule: momentum, flow, smart-money, derivatives.
6. Them walk-forward sweep cho score/confidence/RSI/RR.

## Canh bao

Neu ep win rate len 80% bang TP rat gan va SL rat xa, bot co the thang nhieu lenh nho nhung thua nang mot lenh lon. Ban nang cap nay di theo huong nguoc lai: giam so lenh, yeu cau confirmation sach hon, va bao ve lenh dung huong bang breakeven/trailing.
