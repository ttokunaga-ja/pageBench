import nltk
import ssl

# SSL証明書エラー回避のため、検証をスキップするコンテキストを設定
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    # 古い Python では存在しない場合がある
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

print("Downloading NLTK resources...")
nltk.download('punkt_tab')
nltk.download('averaged_perceptron_tagger_eng')
nltk.download('averaged_perceptron_tagger')
print("NLTK resources downloaded successfully.")
