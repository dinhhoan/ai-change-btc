# Giai thich ti trong so tu hoc

## Muc dich

Phan `learner` khong tu tao lenh rieng. No quan sat cac tin hieu da phat ra, doi mot so tick, sau do xem gia di dung hay sai huong. Neu mot thanh phan thuong xuat hien trong cac lenh dung, trong so cua thanh phan do tang. Neu thuong xuat hien trong cac lenh sai, trong so giam.

Cong thuc y tuong:

`trong_so_moi = trong_so_goc * (1 + edge_hoc_duoc)`

Sau do he thong chuan hoa lai tong trong so de diem tin hieu khong bi phong dai vo ly.

## Cac tham so trong config

- `enabled`: bat/tat bo tu hoc. Khi false, bot dung trong so goc.
- `log_path`: file ghi lai moi quyet dinh va ket qua sau khi kiem chung.
- `state_path`: file luu edge da hoc de lan chay sau khong mat tri nho.
- `outcome_horizon_ticks`: so nhip can doi truoc khi cham ket qua mot tin hieu. Vi du `12` nghia la doi 12 tick roi moi xem tin hieu do dung hay sai.
- `min_abs_return`: bien dong toi thieu de tinh la thang/thua. Neu gia di qua it thi tinh la scratch, khong cap nhat edge.
- `learning_rate`: toc do cap nhat edge. Cao hon thi hoc nhanh hon nhung de nhiem noise; thap hon thi cham nhung on dinh hon.

## Cac thanh phan trong bang UI

- `momentum` / Da gia: gia dang tang/giam nhanh trong ngan han.
- `whale` / Dong ca map: net USD tu cac vi hoac cum lon.
- `flow` / Ap luc mua ban: buy pressure va volume tren tape.
- `trend` / Xu huong EMA: EMA nhanh/cham de tranh vao nguoc nhip.
- `rsi` / RSI: loc vung qua nong/qua lanh.
- `smart_money` / Cum smart money: cum lenh 5 phut co dong thuan cao.
- `derivatives` / Phai sinh: long/short ratio, taker buy/sell, open interest.

## Cach doc UI

- `Edge hoc duoc > 0`: thanh phan nay gan day ho tro lenh dung, bot se tang niem tin vao no.
- `Edge hoc duoc < 0`: thanh phan nay gan day gay nhieu tin hieu sai, bot se ha trong so.
- `Trong so dang dung`: trong so cuoi cung duoc dua vao cong thuc tinh score LONG/SHORT.

## Luu y khi toi uu

Khong nen tang `learning_rate` qua cao khi mau con it. Neu moi co vai chuc ket qua, learner de bi "hoc nham" theo mot doan market ngan. Nen uu tien:

- giu `learning_rate` tu 0.05 den 0.10;
- tang chat luong filter vao lenh truoc khi tin learner;
- theo doi rieng win rate theo regime: trend, sideway, volatility cao;
- reset hoac giam tin vao learner neu market doi regime qua manh.
