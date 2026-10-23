import json
import glob

def merge_fixtures(output_file="seed.json"):
    merged_data = []

    # cari semua file yang cocok dengan pola data_seed*.json
    for file in glob.glob("*_seed.json"):
        print(f"📂 Membaca {file} ...")
        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                merged_data.extend(data)
            else:
                print(f"⚠️  Skip {file}, bukan format list JSON")

    # simpan gabungan
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(merged_data, f, indent=2, ensure_ascii=False)

    print(f"✅ Fixtures berhasil digabung jadi {output_file}")


if __name__ == "__main__":
    merge_fixtures("seed.json")
