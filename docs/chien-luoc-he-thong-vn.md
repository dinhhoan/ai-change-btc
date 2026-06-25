# Chien luoc he thong Whale Signal Lab

Cap nhat: 2026-06-18.

Tai lieu nay tong hop bang tieng Viet nhung chien luoc da duoc xay dung trong project, muc tieu cua tung lop logic, cach chung ket hop voi nhau, va huong nang cap tiep theo.

## 1. Triet ly chung

He thong nay khong duoc thiet ke de "vao lenh vi mot tin hieu duy nhat". Toan bo project duoc xay theo mo hinh nhieu lop xac nhan:

- gia va dong luong thi truong
- ap luc mua ban thuc te
- dong tien ca map / whale flow
- tam ly derivatives
- cum hanh vi dang dong pha
- bo loc chi phi vao lenh
- lop tu hoc de dieu chinh trong so

Neu cac lop nay cung huong, he thong moi uu tien LONG hoac SHORT. Neu chung xung dot, he thong giam do tin cay hoac giu FLAT.

## 2. Chien luoc nen: market state + order flow

Day la lop co ban nhat, luon chay truoc tat ca cac lop khac.

He thong doc du lieu tu Binance:

- gia dong cua gan nhat
- quote volume
- taker buy quote

Tu do tinh ra:

- momentum ngan han
- buy pressure
- EMA nhanh va EMA cham
- trend score
- RSI
- volatility penalty

Y nghia:

- momentum cho biet gia dang tang hay giam trong cua so gan
- buy pressure cho biet luc mua chu dong co dang chiem uu the khong
- EMA trend giup tranh vao lenh nguoc xu huong qua som
- RSI giup tranh mua khi qua nong hoac short khi qua kiet
- volatility penalty giup bo bot lenh trong luc nhiu

Day la tang "chan de". Neu khong co xac nhan toi thieu tu tang nay, cac tin hieu khac khong duoc phep ep he thong vao lenh.

## 3. Chien luoc whale flow

Ban dau, he thong theo doi cac giao dich ERC-20 lon tu vi da gan nhan tren EVM chain thong qua Etherscan/BscScan API.

Logic:

- tien di vao san giao dich duoc xem la ap luc phan phoi, nghieng SHORT
- tien rut ra khoi san duoc xem la ap luc tich luy, nghieng LONG
- stablecoin cung duoc tinh tac dong nhung voi he so nhe hon

Chien luoc nay khong dung de vao lenh mot minh. No la mot "dong tien bo tro", rat huu ich khi di cung:

- trend cung huong
- derivatives cung huong
- cum lenh 5 phut cung huong

Neu whale flow rat manh nhung trend va order flow nguoc lai, he thong uu tien dung ngoai.

## 4. Chien luoc derivatives sentiment 5 phut

Day la lop du lieu quan trong da duoc bo sung de doc tam ly tren Binance Futures.

He thong doc cac endpoint cong khai:

- global long/short account ratio
- top trader long/short position ratio
- taker buy/sell volume ratio
- open interest history

Y nghia chien luoc:

- global long/short ratio duoc doc theo kieu phan bien
  - dam dong nghieng qua mot phia thi can than
- top trader ratio duoc doc theo kieu dong thuan xu huong
  - top trader nghieng phia nao thi do la dau vet co gia tri hon
- taker buy/sell ratio cho thay ap luc vao lenh chu dong trong ngan han
- open interest change cho thay lenh moi co dang duoc mo them hay khong

Tam ly derivatives duoc quy thanh `derivatives_score`, sau do di vao bo may cham diem trung tam.

## 5. Chien luoc cum lenh 5 phut tren Binance

Day la huong nang cap moi nhat va gan voi muc tieu cua ban nhat.

### Van de thuc te

Trong san Binance, khong the thay "10.000 vi nguoi dung that" ben trong order book mot cach cong khai. Vi vay, he thong khong nen gia vo la dang nhin thay tung vi ca nhan trong san.

### Cach lam kha thi

Thay vi co gang doan vi noi san, he thong lay:

- `aggTrades` trong 5 phut gan nhat
- long/short ratio
- taker buy/sell
- open interest

Sau do quy doi thanh "cum hanh vi dong pha".

### Cach gom cum

Moi giao dich tong hop se duoc quy ve cac dac trung:

- symbol
- huong LONG hoac SHORT
- bucket thoi gian ngan
- size band
- derivative bias

Tu do he thong tao ra `cluster_hint` va gom cac lenh co hanh vi giong nhau thanh mot cum.

### Cach cham diem cum

Moi cum duoc danh gia bang:

- tong USD
- so nhip lenh / trade units
- do dong pha theo thoi gian
- muc do cung huong voi derivatives

Ket qua la:

- `sync_score`
- `historical_edge`
- `score`
- `confidence`

Lop nay hien nay la cach thay the thuc dung nhat cho y tuong "phat hien doi lai / nhom dang danh cung nhau trong san".

## 6. Chien luoc Strategy Gate

Day la bo loc ra quyet dinh cuoi cung.

He thong khong vao lenh chi vi `raw_score` duong hoac am. Truoc khi vao lenh, no con kiem tra:

- co du so phieu bullish hoac bearish doc lap khong
- EMA co dang xung dot voi huong vao lenh khong
- RSI co qua nong / qua lanh khong
- volatility co qua nhieu khong

Vi du:

- LONG can du xac nhan tang va khong duoc nguoc xu huong EMA
- SHORT can du xac nhan giam va khong duoc short vao luc RSI qua kiet

Neu khong qua gate, he thong tra ve FLAT du `raw_score` co nghieng ve mot phia.

## 7. Chien luoc vao lenh co tinh phi

Day la lop bao ve cuc ky quan trong de tranh "tin hieu dung nhung lenh van lo vi phi".

Truoc moi lenh vao, he thong uoc tinh:

- fee san
- slippage
- gas/network cost

Sau do so voi `expected_edge`.

Cong thuc khai niem:

- `total_cost = fee + slippage + gas`
- `expected_edge = khoang cach gia ky vong * khoi luong`

He thong bo qua lenh neu:

- `expected_edge < total_cost * min_edge_cost_multiple`

Y nghia:

- khong vao lenh khi edge qua mong
- giam overtrade
- giup paper trading thuc te hon

## 8. Chien luoc paper trading va danh gia hieu qua

Project khong vao lenh that. No paper trade de danh gia:

- lai lo rong
- ti le thang
- so lenh thang / thua
- PnL da chot
- PnL dang mo
- tong phi
- tong gas/network cost

Muc tieu cua lop nay la bien moi y tuong thanh mot gia thuyet co the do duoc.

No giup tra loi cac cau hoi:

- tin hieu nao co edge that
- nguong confidence nao hop ly
- phi co dang an het loi nhuan khong
- nen giam size hay tang size

## 9. Chien luoc tu hoc trong so

Day la lop giup he thong khong bi dong cung.

Moi tin hieu sau khi sinh ra se duoc ghi log. Sau mot so tick nhat dinh, he thong kiem tra:

- neu tin hieu dung, tang trong so cho nhung thanh phan da day dung huong
- neu tin hieu sai, giam trong so cho nhung thanh phan da day sai huong

Nhung thanh phan hien duoc hoc gom:

- momentum
- whale
- flow
- trend
- rsi
- smart_money
- derivatives

Y nghia:

- neu derivatives dang co gia tri trong giai doan hien tai, trong so cua no se tang
- neu cum smart money bi nhieu, trong so cua no se giam
- he thong tu dong thich nghi theo che do thi truong

## 10. Chien luoc giao dien va demo

Giao dien HTML nho duoc lam de:

- xem quyet dinh LONG / SHORT / FLAT
- xem lai lo theo thoi gian
- thay cost review truoc lenh
- theo doi cum lenh 5 phut
- xem long/short ratio
- theo doi trong so tu hoc

Phan giao dien duoc viet theo huong demo nghien cuu, giup nhin duoc:

- he thong dang nghi gi
- vi sao no vao lenh hay bo qua
- thanh phan nao dang dong gop manh nhat

## 11. Chien luoc ma hai ben da dieu chinh theo thoi gian

Trong qua trinh lam viec, he thong da di qua cac giai doan:

1. Theo doi whale flow + market momentum
2. Them smart-money cluster theo y tuong nhom vi dong thuan
3. Them derivatives sentiment tu Binance Futures
4. Them lop tu hoc trong so
5. Them cost guard truoc vao lenh
6. Dich giao dien sang tieng Viet, hien thi lai lo ro hon
7. Bo cach mo phong "vi noi san" khong thuc te
8. Chuyen sang cum lenh 5 phut duoc suy ra tu du lieu cong khai tren Binance

Day la thay doi rat quan trong: tu "cau chuyen nghe co ve hay" sang "thiet ke co the thu duoc bang du lieu that".

## 12. Gioi han hien tai

He thong hien nay van co cac gioi han:

- khong thay duoc user wallet thuc ben trong CEX
- `aggTrades` la du lieu tong hop, khong phai danh tinh trader
- whale on-chain va orderflow trong san van la hai the gioi khac nhau
- chua co backtest day du theo kho du lieu lon
- learner hien van don gian, chua phan loai theo regime

Noi ngan gon: day la mot research lab tot, chua phai bo may auto-trading production.

## 13. Huong nang cap de tang ti le win

Nhung huong hop ly nhat de nang cap tiep:

- luu toan bo tick, signal, order, outcome vao SQLite hoac DuckDB
- backtest rieng tung lop tin hieu theo khung 5m / 15m / 1h
- tach rieng setup breakout, trend-follow, mean-reversion
- them che do chi giao dich khi BTC co trend ro
- theo doi funding rate va basis cung open interest
- xep hang cum lenh nao thuc su co edge sau 100, 500, 1000 lan xuat hien
- ghep orderflow trong san voi on-chain outflow/inflow de tao tin hieu cap cao hon

## 14. Ket luan

Chien luoc chung cua project khong phai la "tim mot chi bao than thanh". No la:

- lay nhieu nguon du lieu that
- quy thanh cac lop tin hieu de doc hanh vi thi truong
- chi vao lenh khi co du xac nhan
- tinh du chi phi truoc lenh
- ghi log va tu hoc de biet lop nao dang thuc su hieu qua

Neu viet gon thanh mot cau, thi day la:

"He thong uu tien giao dich khi dong luong, derivatives, cum lenh 5 phut, va bo loc rui ro cung dong thuan; neu khong dong thuan thi dung ngoai."
