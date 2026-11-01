import argparse
import json
from .core import media_kind, register_asset, verify_media
from . import watermark
from .watermark import generate_key


def engine(file):
    if media_kind(file) == 'video':
        from . import video
        return video
    return watermark


parser = argparse.ArgumentParser(description='Local media POC')
sub = parser.add_subparsers(dest='command', required=True)
register = sub.add_parser('register')
register.add_argument('file')
register.add_argument('--creator', required=True)
lookup = sub.add_parser('verify')
lookup.add_argument('file')
key = sub.add_parser('keygen')
key.add_argument('keyfile')
mark = sub.add_parser('watermark')
mark.add_argument('file')
mark.add_argument('output')
mark.add_argument('--key', required=True)
check = sub.add_parser('check-watermark')
check.add_argument('file')
check.add_argument('--key', required=True)
args = parser.parse_args()
if args.command == 'register':
    result = register_asset(args.file, args.creator)
elif args.command == 'verify':
    result = verify_media(args.file)
elif args.command == 'keygen':
    generate_key(args.keyfile)
    result = {'key_created': args.keyfile}
elif args.command == 'watermark':
    result = engine(args.file).embed(args.file, args.output, args.key)
else:
    result = engine(args.file).verify(args.file, args.key)
print(json.dumps(result, indent=2))
