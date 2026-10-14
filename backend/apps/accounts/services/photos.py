"""Profile photos: validate an upload, cut it square, store two small JPEGs.

Everything that arrives is re-encoded: the stored bytes are produced by Pillow from the decoded
pixels, so metadata (EXIF, GPS, embedded profiles) and anything a hostile file hides after the
image data never reaches another person's browser or contacts app. The photo lives in the
database (``UserProfile``), a few tens of kilobytes per person.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from backend.apps.accounts.models import MailUser, UserProfile

if TYPE_CHECKING:
    from PIL import Image

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_SOURCE_PIXELS = 25_000_000  # a 5000 x 5000 photo; larger is refused before it is decoded
MIN_SIDE = 64
LARGE = 256  # shown in the account page and sent to contacts apps (vCard PHOTO)
SMALL = 96  # lists and the header avatar (up to 48 px on a 2x screen)
JPEG_QUALITY = 88
FORMATS = {'JPEG', 'PNG', 'WEBP', 'GIF'}


class PhotoError(Exception):
    """A photo that cannot be used; the message is meant for the person who uploaded it."""


@dataclass(frozen=True)
class Crop:
    """The square the person chose, as fractions of the (upright) picture.

    ``x`` and ``y`` are the left and top edge as a share of width and height; ``size`` is the
    side as a share of the shorter edge. Fractions keep the browser and the server agreeing
    whatever the picture's size or EXIF rotation.
    """

    x: float
    y: float
    size: float

    @classmethod
    def parse(cls, x: str, y: str, size: str) -> Crop | None:
        try:
            crop = cls(float(x), float(y), float(size))
        except (TypeError, ValueError):
            return None
        if not all(0.0 <= v <= 1.0 for v in (crop.x, crop.y)) or not 0.05 <= crop.size <= 1.0:
            return None
        return crop


def _square(image: Image.Image, crop: Crop | None) -> tuple[int, int, int, int]:
    width, height = image.size
    short = min(width, height)
    if crop is None:
        side = short
        left, top = (width - side) // 2, (height - side) // 2
    else:
        side = max(MIN_SIDE // 2, min(short, round(crop.size * short)))
        left = min(max(0, round(crop.x * width)), width - side)
        top = min(max(0, round(crop.y * height)), height - side)
    return left, top, left + side, top + side


def process(data: bytes, crop: Crop | None = None) -> tuple[bytes, bytes]:
    """Return ``(large, small)`` JPEG bytes for an uploaded picture, or raise ``PhotoError``."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not data:
        raise PhotoError(_('Choose a picture to upload.'))
    if len(data) > MAX_UPLOAD_BYTES:
        raise PhotoError(_('That picture is larger than 5 MB.'))
    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
    try:
        opened = Image.open(io.BytesIO(data))
        if opened.format not in FORMATS:
            raise PhotoError(_('Use a JPEG, PNG, WebP or GIF picture.'))
        width, height = opened.size
        if width * height > MAX_SOURCE_PIXELS:
            raise PhotoError(_('That picture is too large. Use one under 25 megapixels.'))
        if min(width, height) < MIN_SIDE:
            raise PhotoError(
                _('That picture is too small. Use one at least %(px)s pixels on each side.')
                % {'px': MIN_SIDE}
            )
        opened.seek(0)  # the first frame of a GIF
        opened.load()
        upright = ImageOps.exif_transpose(opened)
    except PhotoError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise PhotoError(_('That file is not a picture we can read.')) from exc

    image: Image.Image
    if upright.mode in ('RGBA', 'LA', 'P'):
        rgba = upright.convert('RGBA')
        image = Image.new('RGB', rgba.size, (255, 255, 255))
        image.paste(rgba, mask=rgba.getchannel('A'))
    else:
        image = upright.convert('RGB')

    square = image.crop(_square(image, crop))
    out: list[bytes] = []
    for side in (LARGE, SMALL):
        buffer = io.BytesIO()
        square.resize((side, side), Image.Resampling.LANCZOS).save(
            buffer, 'JPEG', quality=JPEG_QUALITY, optimize=True, progressive=False
        )
        out.append(buffer.getvalue())
    return out[0], out[1]


class PhotoService:
    @staticmethod
    def set_photo(user: MailUser, data: bytes, crop: Crop | None = None) -> UserProfile:
        large, small = process(data, crop)
        with transaction.atomic():
            profile: UserProfile = UserProfile.objects.get_or_create(user=user)[0]
            profile.photo_large = large
            profile.photo_small = small
            profile.photo_sha256 = hashlib.sha256(large).hexdigest()
            profile.photo_updated_at = timezone.now()
            profile.save(
                update_fields=['photo_large', 'photo_small', 'photo_sha256', 'photo_updated_at']
            )
        _changed()
        return profile

    @staticmethod
    def remove_photo(user: MailUser) -> bool:
        removed = (
            UserProfile.objects.filter(user=user)
            .exclude(photo_sha256='')
            .update(photo_large=None, photo_small=None, photo_sha256='', photo_updated_at=None)
        )
        if removed:
            _changed()
        return bool(removed)

    @staticmethod
    def get(user_id: object, size: str = 'small') -> tuple[bytes, str] | None:
        """``(jpeg bytes, sha256)`` of a login's photo, or ``None`` when it has none."""
        field = 'photo_large' if size == 'large' else 'photo_small'
        row = (
            UserProfile.objects.filter(user_id=user_id)
            .exclude(photo_sha256='')
            .values_list(field, 'photo_sha256')
            .first()
        )
        if not row or not row[0]:
            return None
        return bytes(row[0]), row[1]

    @staticmethod
    def photo_version(user: MailUser) -> str:
        """Short cache-busting token for the person's photo URL; empty without a photo."""
        sha = (
            UserProfile.objects.filter(user=user)
            .exclude(photo_sha256='')
            .values_list('photo_sha256', flat=True)
            .first()
        )
        return (sha or '')[:12]

    @staticmethod
    def set_directory_hidden(user: MailUser, hidden: bool) -> None:
        profile: UserProfile = UserProfile.objects.get_or_create(user=user)[0]
        if profile.directory_hidden != hidden:
            profile.directory_hidden = hidden
            profile.save(update_fields=['directory_hidden'])
            _changed()


def _changed() -> None:
    """Ask for the contact directory to be republished once this change is committed."""
    from backend.apps.accounts.services.directory import DirectoryService

    DirectoryService.request_publish()
