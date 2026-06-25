# Ke hoach vao lenh tang kha nang chien thang

Cap nhat: 2026-06-18.

Tai lieu nay tom tat ke hoach vao lenh thuc dung cho Whale Signal Lab sau khi chuyen sang cum lenh 5 phut tu Binance va RR 1:3.

## 1. Muc tieu

He thong khong uu tien giao dich nhieu. Muc tieu la:

- giam overtrade
- giam phi bi an mon
- giu duoc lenh tot lau hon
- chi vao lenh khi co xac nhan doc lap
- thoat lenh bang RR 1:3 thay vi doi tin hieu lat qua lat lai

## 2. Dieu kien vao lenh

Chi vao lenh khi dat du 3 tang:

1. Market state
- gia co huong ro hon FLAT
- flow score cung huong voi lenh
- trend score khong xung dot

2. Cum lenh 5 phut
- smart money score co huong ro
- sync score khong qua thap
- khong vao lenh neu cum lenh qua manh nhung dao chieu lien tuc

3. Derivatives
- top ratio va taker ratio khong xung dot manh voi huong vao lenh
- open interest giam qua nhanh thi han che trend-follow muon

## 3. Luat vao lenh de tang ti le win

- uu tien lenh cung huong voi trend ngan han
- uu tien lenh co it nhat 2 xac nhan doc lap
- tranh vao lenh khi RSI qua cang
- tranh vao lai ngay sau khi vua thoat lenh
- khi dang co position thi khong scale vao them lien tuc

## 4. RR 1:3

Moi lenh moi deu co trade plan:

- 1 phan rui ro
- 3 phan loi nhuan ky vong

He thong dat:

- stop-loss dua tren risk band gan nhat va muc stop toi thieu
- take-profit = 3 x risk

Tac dung:

- chot loi nhuan co ky luat
- khong can doi signal doi mau moi thoat
- giam so lan flip vi the

## 5. Giam overtrade

De giam phi va nhieu:

- co cooldown sau khi thoat lenh
- co minimum holding ticks
- chi cho phep dao chieu som neu signal nguoc du manh

## 6. Muc uu tien tiep theo

1. Tach setup theo che do thi truong
- trend-follow
- pullback
- panic reversal

2. Tach weighting theo symbol
- BTC
- ETH
- SOL

3. Xep hang cum lenh
- cum nao co edge that sau 100, 300, 500 lan xuat hien

4. Giam trong so learner cu
- reset hoac decay bot ky uc cu
- tranh de regime cu keo sai quyet dinh hien tai

## 7. Nguyen tac van hanh

Neu muon tang kha nang chien thang, uu tien:

- it lenh hon
- lenh ro hon
- RR ro rang hon
- phi re hon
- co cooldown

Khong uu tien:

- nhay vao ra lien tuc moi 1-2 giay
- vao lenh khi du lieu 5 phut chua doi ma signal chi rung nhe
