use aes_gcm::aead::{Aead, KeyInit, Payload};
use aes_gcm::{Aes256Gcm, Nonce};
use hkdf::Hkdf;
use sha2::Sha256;
use x25519_dalek::{PublicKey, StaticSecret};

const CLIENT_PRIV: &str = "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a";
const ROBOT_PRIV: &str = "5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb";
const CLIENT_PUB: &str = "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a";
const ROBOT_PUB: &str = "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f";
const SALT: &str = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f";
const EXPECT_SHARED: &str = "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742";
const EXPECT_KEY: &str = "9d9a6c54ea37a599ec06d5b920d376bc6010335484e4b2f5a8ce8478bde57121";
const PLAINTEXT: &str = r#"{"ssid":"DS1002","psk":"TestPass123"}"#;
const BLOB: &str = "000102030405060708090a0bf3165fffb4218ea434859831a0c65bd7fb9865ee6114dbcd566814208a0f4b7c8eb32d46b1a2606e4ec505decb302f170292594d50";
const INFO: &[u8] = b"microduck/wifi-provision/v1";
const AAD: &[u8] = b"net.connect";

fn h(s: &str) -> Vec<u8> { hex::decode(s).unwrap() }

fn main() {
    let mut pass = 0usize;
    let mut total = 0usize;
    macro_rules! ck {
        ($name:expr, $cond:expr) => {{
            total += 1;
            let ok = $cond;
            if ok { pass += 1; }
            println!("  {}  {}", if ok { "PASS" } else { "FAIL" }, $name);
            assert!(ok, "negative control FAILED: {}", $name);
        }};
    }

    // 1) X25519: 双方各用自己的私钥 + 对端公钥，应得同一 shared
    let client_secret = StaticSecret::from(<[u8; 32]>::try_from(h(CLIENT_PRIV)).unwrap());
    let robot_secret = StaticSecret::from(<[u8; 32]>::try_from(h(ROBOT_PRIV)).unwrap());
    let robot_pub = PublicKey::from(<[u8; 32]>::try_from(h(ROBOT_PUB)).unwrap());
    let client_pub = PublicKey::from(<[u8; 32]>::try_from(h(CLIENT_PUB)).unwrap());
    let shared_a = client_secret.diffie_hellman(&robot_pub);
    let shared_b = robot_secret.diffie_hellman(&client_pub);
    ck!("X25519 shared = RFC7748 权威 K", hex::encode(shared_a.as_bytes()) == EXPECT_SHARED);
    ck!("X25519 双方对称", shared_a.as_bytes() == shared_b.as_bytes());

    // 2) HKDF-SHA256: ikm = shared || client_pub || robot_pub
    let mut ikm = Vec::new();
    ikm.extend_from_slice(shared_a.as_bytes());
    ikm.extend_from_slice(client_pub.as_bytes());
    ikm.extend_from_slice(robot_pub.as_bytes());
    let hk = Hkdf::<Sha256>::new(Some(&h(SALT)), &ikm);
    let mut key = [0u8; 32];
    hk.expand(INFO, &mut key).unwrap();
    ck!("会话 key = Python HKDF", hex::encode(key) == EXPECT_KEY);

    // 3) AES-256-GCM 解封 Python 生成的 blob（AAD 通过 Payload 指定）
    let cipher = Aes256Gcm::new_from_slice(&key).expect("AES-256 key len");
    let blob = h(BLOB);
    let nonce = Nonce::from_slice(&blob[..12]);
    let pt = cipher.decrypt(nonce, Payload { msg: &blob[12..], aad: AAD }).expect("GCM tag mismatch");
    ck!("Rust 解开 Python 密文 = plaintext", pt == PLAINTEXT.as_bytes());

    // 4) 负对照：篡改密文必失败
    let mut bad = blob.clone();
    bad[12] ^= 1;
    let rejected = cipher.decrypt(Nonce::from_slice(&bad[..12]), Payload { msg: &bad[12..], aad: AAD }).is_err();
    ck!("负对照: 篡改密文 GCM 解封失败", rejected);

    // 5) 负对照：AAD 不符必失败
    let mut nb = [0u8; 12]; nb.copy_from_slice(nonce);
    let enc_forget = cipher.encrypt(Nonce::from_slice(&nb), Payload { msg: PLAINTEXT.as_bytes(), aad: b"net.forget" }).unwrap();
    let aad_rejected = cipher.decrypt(Nonce::from_slice(&nb), Payload { msg: &enc_forget, aad: AAD }).is_err();
    ck!("负对照: AAD 不符解封失败", aad_rejected);

    println!("\nSELFTEST: {}/{} passed", pass, total);
    assert_eq!(pass, total);
}
