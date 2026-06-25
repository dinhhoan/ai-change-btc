# Deploy len Google Cloud Free Tier e2-micro

Huong dan nay chay bot nhu mot `systemd` service tren VM Ubuntu. Mac dinh service chay paper/demo, gui Telegram khi co lenh vao, va mo dashboard o port `8765`.

## 1. Tao VM mien phi

1. Vao Google Cloud Console, tao project moi.
2. Tao VM Compute Engine:
   - Machine type: `e2-micro`
   - Region nen chon vung Free Tier hop le cua Google Cloud.
   - OS: Ubuntu 24.04 LTS hoac Ubuntu 22.04 LTS.
   - Disk: Standard persistent disk, dung luong nho de tranh vuot free tier.
3. Firewall:
   - Neu chi can Telegram alert, khong mo port `8765` ra internet.
   - Neu muon xem dashboard tu trinh duyet, tao firewall rule TCP `8765` va gioi han source IP ve IP nha ban.

## 2. Clone source tu GitHub len VM

SSH vao VM tu nut `SSH` trong Google Cloud Console, sau do chay:

```bash
sudo apt-get update
sudo apt-get install -y git
sudo mkdir -p /opt/crypto-whale-radar
sudo chown -R "$USER:$USER" /opt/crypto-whale-radar
git clone https://github.com/dinhhoan/ai-change-btc.git /opt/crypto-whale-radar
```

Neu repo dang private, dung SSH URL va them SSH key cua VM vao GitHub Deploy keys.

## 3. Cai service

Tren VM:

```bash
cd /opt/crypto-whale-radar
chmod +x deploy/install_google_cloud_vm.sh
./deploy/install_google_cloud_vm.sh
```

Mo file env:

```bash
sudo nano /opt/crypto-whale-radar/.env
```

Dien:

```bash
TELEGRAM_ENABLED=1
TELEGRAM_BOT_TOKEN=token_bot_moi
TELEGRAM_CHAT_ID=-1003984806512
PYTHONUNBUFFERED=1
```

Nen tao token bot moi bang BotFather truoc khi deploy, vi token cu da tung hien tren man hinh.

## 4. Start va kiem tra

```bash
sudo systemctl enable --now crypto-whale-radar
sudo systemctl status crypto-whale-radar
sudo journalctl -u crypto-whale-radar -f
```

Neu mo firewall port `8765`, dashboard se nam tai:

```text
http://VM_EXTERNAL_IP:8765/
```

Kiem tra API tren VM:

```bash
curl -s http://127.0.0.1:8765/api/state
curl -s "http://127.0.0.1:8765/api/tick?steps=3"
```

## 5. Lenh van hanh nhanh

Restart bot:

```bash
sudo systemctl restart crypto-whale-radar
```

Xem log realtime:

```bash
sudo journalctl -u crypto-whale-radar -f
```

Tat bot:

```bash
sudo systemctl stop crypto-whale-radar
```

Cap nhat source moi:

```bash
sudo systemctl stop crypto-whale-radar
cd /opt/crypto-whale-radar
git pull
./deploy/install_google_cloud_vm.sh
sudo systemctl restart crypto-whale-radar
```
