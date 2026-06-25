# Polymarket Quant Bot Research - 2026-06-21

## Ket luan nhanh

Khong nen theo duoi muc tieu "80% win rate" nhu mot KPI tuyet doi. Mot bot co tiem nang can toi uu expectancy:

`Expectancy = win_rate * avg_win - loss_rate * avg_loss - fee - slippage`

Case Polymarket trong bai viet nguoi dung dua co win rate 39% nhung van lai nho payoff lech va lap lai setup rat nhieu lan. Voi crypto futures/scalp, win rate cao hon co the tot, nhung neu RR thap, phi/slippage cao, hoac vao lenh qua day thi van thua.

## Dieu co the hoc tu bot Polymarket

1. San mispricing, khong san cam xuc
   - Bot tim thi truong "short crypto" co odds chua phan anh day du bien dong.
   - Tuong duong voi crypto dashboard hien tai: san luc Binance orderflow va cum smart money da ro, nhung AI/derivatives/gia chua confirm het.

2. Lap lai edge nho
   - Loi nhuan den tu nhieu lenh nho, khong phu thuoc mot lenh lon.
   - Dashboard nen uu tien playbook: scan -> confirm -> size -> execute -> review.

3. Quan tri fill, spread, phi
   - Polymarket co orderbook CLOB, can tinh spread, depth, fill price va fee truoc khi vao.
   - Crypto bot hien tai da co cost gate, nen tiep tuc giu chat phan nay.

## Nguon nghien cuu chinh

- Polymarket docs mo ta he thong co API/SDK cho market data va trading: https://docs.polymarket.com/
- Trading API la hybrid CLOB: matching offchain, settlement onchain, co public/L1/L2 methods va yeu cau auth khac nhau: https://docs.polymarket.com/trading/overview
- Orderbook API co endpoint public, bids/asks, midpoint/spread, fill price/slippage va websocket event realtime: https://docs.polymarket.com/trading/orderbook
- Market data docs goi y cach fetch active/high volume markets va cache/refresh hop ly: https://docs.polymarket.com/market-data/fetching-markets
- Fee docs neu ro cong thuc fee va cac caveat ve precision: https://docs.polymarket.com/trading/fees

## Canh bao tu nghien cuu/hoc thuat

- Ghost Fills / settlement risk: nghien cuu "The Ghosts of Polymarket" chi ra khoang trong giua matching offchain va settlement onchain co the tao reverted fills va chien luoc tan cong.
- Arbitrage Polymarket khong de an: nghien cuu NBA markets thay co hoi single-market hiem, median duration ngan, liquidity la nut that.
- Public websocket trade direction khong du tin cay tuyet doi: nghien cuu microstructure Polymarket cho thay huong trade tu public feed chi khop onchain khoang 59%, nen neu lam bot that phai xac minh bang onchain OrderFilled events.
- Non-retail/HFT chiem ty trong lon: nghien cuu fill-side cho thay nhom whale/high-frequency/power-trader chiem phan lon notional, nen bot moi phai uu tien latency, fill quality va risk cap.

## Huong di cho project nay

### 1. Uu tien hien tai: Binance orderflow scalp

Da phu hop voi project hien tai nhat vi co BTC/ETH/SOL, cum lenh 5 phut, pressure, taker ratio, derivatives, RSI va paper trade.

Can tiep tuc cai tien:

- Loc cac cum co dong thuan cao, conflict thap.
- Vao lenh khi co it nhat 3/5 xac nhan: net orderflow, buy/sell pressure, taker ratio, derivatives, RSI khong qua nong.
- Bat buoc hien Entry, SL, TP, ly do vao/khong vao.
- Ghi lai moi lenh de hoc nguoc lai setup nao co edge that.

### 2. Huong tiep theo: Polymarket-style mispricing scanner

Chua nen auto-trade ngay. Nen lam watcher truoc:

- Fetch active/high-volume crypto markets tren Polymarket.
- Subscribe orderbook websocket.
- Tinh fair odds tu Binance price, implied move, thoi gian con lai, volatility.
- Chi bao tin hieu khi `fair_price - best_ask` lon hon spread + fee + slippage buffer.
- Uoc tinh fill size bang depth, khong dung midpoint lam gia vao.
- Luu lai ket qua de backtest: signal time, fair odds, best bid/ask, fill estimate, outcome.

### 3. Huong sau: OSINT/narrative edge

Co tiem nang voi prediction markets, nhung rui ro nhieu:

- Tin tuc/X co noise cao.
- Can deterministic validation: nguon nao, thoi diem nao, tac dong den market nao.
- Khong de LLM tu "tuong tuong" su kien; LLM chi nen tom tat va gan nhan, engine quyet dinh phai co rule/score ro.

## Thay doi UI da ap dung

Them "Quant Bot Playbook" vao dashboard:

- Edge scanner: cặp/sóng mạnh nhất từ orderflow.
- Repeat setup: proposal/cụm đáng chú ý nhất.
- Risk/cost gate: lý do chưa vào hoặc vị thế đang mở.
- Execution state: số lệnh paper, trạng thái quản trị.
- Flow: Scan -> Confirm -> Size -> Execute -> Review.

Muc tieu la de nguoi dung nhin vao biet bot dang canh lenh nao, da du dieu kien chua, va bi chan o dau.
