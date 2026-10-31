"""Explicit opt-in downloader for the optional Transformers adapter."""
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", help="For example Qwen/Qwen3-8B")
    parser.add_argument("directory")
    args = parser.parse_args()
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=args.repo, local_dir=args.directory)


if __name__ == "__main__":
    main()
