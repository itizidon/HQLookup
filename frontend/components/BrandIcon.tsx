import Image from 'next/image';
import icon from '@/assets/icon.png';

type BrandIconProps = {
  size?: number;
};

export function BrandIcon({ size = 18 }: BrandIconProps) {
  return (
    <Image
      src={icon}
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      style={{ flexShrink: 0 }}
    />
  );
}
