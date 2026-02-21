import os
import shutil
import atexit

def print_pycache_path_for_file(file_path):
    abs_path = os.path.abspath(file_path)
    dir_path = os.path.dirname(abs_path)
    pycache_path = os.path.join(dir_path, '__pycache__')
    print(f"__pycache__ klasörünün yolu: {pycache_path}")

    def remove_pycache():
        if os.path.exists(pycache_path):
            shutil.rmtree(pycache_path)
            print(f"__pycache__ klasörü silindi: {pycache_path}")
        else:
            print(f"__pycache__ klasörü bulunamadı: {pycache_path}")

    atexit.register(remove_pycache)

# Örnek kullanım:
print_pycache_path_for_file(' ')
