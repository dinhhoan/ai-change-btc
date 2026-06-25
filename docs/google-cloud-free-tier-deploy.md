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

## 2. Upload source len VM

Tu may Mac, nen nen thu muc du an:

```bash
cd "/Users/hoantran/Tdhoan"
tar --exclude='crypto-whale-radar/.venv' --exclude='crypto-whale-radar/__pycache__' --exclude='crypto-whale-radar/**/__pycache__' -czf /tmp/crypto-whale-radar.tar.gz crypto-whale-radar
```

Copy len VM. Thay `YOUR_VM_USER` bang username SSH cua VM va `VM_EXTERNAL_IP` bang IP VM:

```bash
scp /tmp/crypto-whale-radar.tar.gz YOUR_VM_USER@VM_EXTERNAL_IP:/tmp/
```

Tren VM:

```bash
sudo mkdir -p /opt
cd /opt
sudo tar -xzf /tmp/crypto-whale-radar.tar.gz
sudo chown -R "$USER:$USER" /opt/crypto-whale-radar
```

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
cd /opt
sudo tar -xzf /tmp/crypto-whale-radar.tar.gz
sudo chown -R "$USER:$USER" /opt/crypto-whale-radar
cd /opt/crypto-whale-radar
./deploy/install_google_cloud_vm.sh
sudo systemctl restart crypto-whale-radar
```
