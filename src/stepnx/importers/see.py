from __future__ import annotations

import base64
import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from stepnx.core.errors import ParseError
from stepnx.importers.nx10 import NX10ImportResult, import_bytes as import_nx10_bytes


SEE_MAGIC = b"STEE"
SEE_VERSION = 1
SEE_HEADER_SIZE = 0x120
SEE_SECTION_TABLE_OFFSET = 0xFC
SEE_SECTION_COUNT = 9
SEE_SPLIT_SLOTS = 200

# StepEdit 5.63 uses one fixed Blowfish key schedule for SEE. The fully
# expanded schedule is embedded instead of pulling a general-purpose crypto
# dependency into the editor for one historical chart format. The packed data
# is little-endian P[18] followed by S[4][256].
_BLOWFISH_SCHEDULE_B85 = (
    '8A4GFxGs0~5TPQZfJu{=T6MN(2BN`~tqS}Lu_s~d1f7G#qt_N2JDtL2#F-E`i|{d40s~ji>eSDLsTFjOir@F@%6yaM(!a;ba5yYB'
    'TcasTL}Np;{cznO?m0D@-wp%Gc{#ElgIid(6gg!?t>x!1w;zfiQyB)Rd;Je$6(Wq1;U>pLXax2sQu?`Ze!zblh!D_~n-yowxWnNs'
    '-sWxbunhdcPH>8Nb)T0RyvHYI3qHOyP6*v*Xj6B^^(`BC%~3xLQjRZncGswUI2*R5GsRa9ePRT*AOZodMSmo<1~;dVXQqUjY|M-g'
    'I`u%iZ-?e<`*Y%1Fxq}e^a}1(#RD}qcHwf6?yJP@d$sF#FPzS(&)Q({T`Mo1UP-HG2Lg&SB}#gHs~5T=X^N=bAqD+p>VWO~+|x%~'
    'aJJQk7XZKeIVTZY+veyrJeYQFnjl8YD~iUH+Xb?3LdXA++B#p6i8GmyQYKinVHih!tzBQk`NNWi0HW&cLgXUH1w(ms#<sG>m&WrX'
    'y#zk9S(u+0hM^Q${_0<_dv0buvP(|F_iX8OTf9l3dC#O$T;<l~Mxg=k%$5z1mJg*|hpcHA{|y>)A6gBigcKPe;>1nL6KApR-wk<A'
    '!~g^_eKPSh1CXZ|NpPLxd@2C3TMpyy+3NJOC%5ddAS>OC-4dbDT2$4GK4?Io0TVe`F-yC__l6PZuqCY^f~blN?lt?%nMztl&SPeh'
    'plMFz7Z&ebPrD%`?8(mjc{cbPcs_`@#XnU6FpKD**R6tlwBr(;IaqMY3~qx)><byDH-rvLAkq=^YNZbt<P*SdZc&CZ)a3tmXnEj>'
    '>EF+49%gTzW6jxewU3GW-|dAJ2F@a8&0qZWcAQ2mP{`2h(5)p^m)hF+5Q1O`<yE%le$XH3e${hDDpaiP1$_Gkn!m?6hOD+`{_~A|'
    '>?9QWc9P~F5Ce%sWV%*lEG~v^w@HorrbGbwiUNyT&or`x(wbhM{S<{GbETo&qwfyk(_xtXFsebXpM&jU1C<~VU4jX${t?h8LsZhf'
    '$|-~C&gS=xM@|8-tQTJARzz25(aTco$7&$MaLh<ff}?$CMDlVWA3WUsGWQzWKz8<Ka4=fkvbgFTJQ#A1Vwj#0_J}AcF+b5YoN|E7'
    '*36WPSG&t59FEtx<h(m*ukV`=h2WF*C#+a7Ss@ypO!-Va%_-CHCL*(|2k8--wF`JQ4=70ku!ECc(`YBtEX1qrrPl^U^;CGp8r0Tk'
    'sez|&DR&9Z`?}esag722h2XJ#0-aiO{T1z!Tr>72NBv0f`r0V}06<!g0NfZ=``ma9nBdn}+#OsgNWS10a9=D<Ow1oCPU>2{X|(7`'
    'VE(7-g|u2QL;U7l*m03zJOcH7u#^VOJR$@U7>Q`^@6ch*Lut3=o&tP2zAx|Sma^rwVF0f;<$lg#TdD^xwU_d!hR#oZ6Rn^0!`L)<'
    '5zZ;dHHzPhzN}(hIa9m4Fo(}@`GXMoq2mVh>U9+My1M=Oq>))_9iPFVAM)aECAQ<b#H>cgtVmUW{iTsxasBEZx9Sl^y#eGYG6O>='
    'Z!i<~rLaeBEEZ9`-iwzAnVe;mEK%KsP5H^(D3=5cC{jFkQrvlxv%_tfXEu>CS1?OX1xNX0v;a!;PK{?uxUOgou8$@zQG-|QmI9Nw'
    'G#BseI&U#Y2kIu;=5S8}9(gPSDts;`NGc-!XZg9&;h<gObE$+5pq7rC<sKBaC{38FWVGzOVDI_PB7-k?D}Ua-P`sxv0>k_F*62Yh'
    '>l$#ti}$Y;ywlo!p4`hI09_2g+m$R=&$99mNj!&OF3Jo8<^6~ZEf`=$h<0i5<TUa)%kw?heMnUpMU8K@<(^OOvq&MU4jJG}+`9F`'
    'ZoytAP&2XFl%EmcX6>~tD)KH+8D~e#*YlZ9R+23dX$qO@8+r6{SCOd^NoLhjod)NsG9#X5N5{ff)}~DwGhlrR8S_JxE>00j#1LKu'
    'u@z&<5qHQ@#FHDzO=a2?$^dN}&3aNdd0yp?rG*y2mUvbdBvfXFn^aH6IU3S~<79BKpV~7oW4!=(!BbZ+`#w-ZN8VGWyslTz*Mqrh'
    '^#8+)^P!u!W~xo>L%GjY^S?13VdAy42Jl`r_**UD8-A8jw?rVc`YTIYPX&Hn0zqPZKb2p`DzIFs%anLenq|kpL9!Sa04s^Dm;X?d'
    '2BI7gEp^8We=y;ug`7>$@yC>?F%<|Lct))XkHs8~9eB?9D|93V7sgABBFog@rh_^a!j7sgB!MHGz^5WRp(#mO4kSeWf27h6)h7qR'
    'AzKJPGI{eB1L!U^PG%}?1~4lSX0ZGO>Cx@CVLKYVfIW2i!fj74#>L3eY@!b~Yu^-Y2x9Dh|JB{>qMq@2<a-eg#ou+fyxcNliQ5L!'
    'h2)U=gtH+M&|SCR`m+*|3{<;;np?54<q`kmfKy9P%TWt4C!ZLpodY61Qi>Ew-khOZnKy}nGtV_d@u*CS2%e#;8i>)O>o$~-{1)I2'
    '+7TSFMb4!Pr`@Mjp)nPQsmn#Q9!c1n<5<E_EAYwY(p1YtGtNyZr^O}jdSL{U#a0|yL6Ku<uyaxb<>}+KDabs6LZB5|f~*8ZMMdh('
    'f)+tL9)gPXhCLxv6=(RoF0Gzp<q8=*t#X5aIJ&C=bfGNAD$S5^PJ^Zd<pNaPAZ47P3P9N%Bvx6sz9E-6v)z5gyqG}%GkvBt1<=`w'
    'n6YYa3S#HYBrJJtHu=A&mwfVT_IBtIrzl&A<agr?wW>yLfNK5P2>#HbvyD{iE}^V6;j(N!Db)c7pG@1<Z|c}NP1An4%{iST!LVPQ'
    'RRE`uB}xgDO$=#P$kqQcnyq-!A8)S+{MyyA_`9P>ZQe}OGg;8Q9pEhh$JC0z75MGL@yl;i<$5MigW(OybdPU%=GKSznjeXk#bKyS'
    '4NbwHxMvaYh91pwVckQcd)UYYo$*<fX`U932@L=(lSWc7#IHL^##4sjpUisCgApvZKUJV8bhOs6>wCU**WraNhf`Thto*an;&Y1m'
    '%0mV5)GdaVj&o!n*Bw)lCeh--+&}QY#i*Tn6FYl($v54o9Ufm$OF$Py6Sf+PFM}r~GiI&)I|g#@S9mSWQnGugIR#dbNrnQPZm?v<'
    'v)@Wm1hE(K$w!BH^Q#jHyb)2#h}>n`_ENNMDeUKXeDNygOr4O^POy@jPrHBvrdRrv1y5He=2GvD*=M9y=uOjr-}=<*vf4;L4m4_E'
    'S|vC+U;f2<aeTp+v|{O($n>DsS|}^s1lnadm$AWk(kbN*tZp<gnUc9o+5kY>3j|9Oj^Gt;6!6+}!Vth_j}y_`t#IvB{fQZtR*a`h'
    'TC!lw1nEeNg~>uOsMY0MeK}w3rW+ejtTKGU)e9#Zx#AOu3d7j04IRC_ikBxmdb<nA;DrEWlG|QBH{)hn*{E#wSJ)w;=o7+1w<wN|'
    '#J1U=$stG-?Zy=s!4E=+leEXavmBE(WrYASkQJD!Le2g*K0EpA?Wx+dz*qVwF^J3^?W}I}r5*E~XB1IdCla)yA`$%(I`p7Fufw5_'
    '=qecg^O>yXLbv^LC^Fm+@4=m|7_}Vxzt+A|dVG@7&}Ml<y4K5dVRNfR*?aUayn5Rui~=^j&InMrZ@P17d(Lf@R+(7JT&4j&bjVMX'
    '(2|~&wFolIS$jAx7Qpql<<^5YT7D*sQl<JMh8aEpSg-rK9C)V&NZ_(b#><lCKOwK~)J_vd>!}+6bx8}YZ+`LJEj4tMGd_<p8_dbW'
    '`Vk=1D{heW>xb3rLWdIFMf)IE@+0v|>E)@)Sz}>KW6lFH*!>U6*yeFnTvphWNc523cF(=T%G==?2_Ck|_(S@|Pbn!+G2KXCKl*T#'
    'kNnz`5E+8V3OSqW{D<kd_O0ZZO0pqG#^B+&Kx^51w^-C2XA+HI@Hkvhy8=y={fuB^Ex6#v0(s=gWRR%!EO48DQ@Wwiw-BjYaYmu#'
    'b*XzI-ifQ{=}VHDsO8#&nU_9W1jN2_Y|9e2eAAP~A3%bei%|8+NAn%q0IzL@E-8VWkYImgDeMe0n(}~RW|@kiM|(&?HfD);z}zF;'
    'yg2V8HTk_8YX+ZhA$8fISIgtFXLaQMcdwatrF(}cxY&xpUhoLnVSHlysMTE_!gyv5PV6qHzw?2$xKSd9D%C4-zcrnQxCem$J_;LI'
    '8_l_2H{n$mtC2CZMvBRT8T>wAECsOT45Bf;>ttuo0;4zdl}#`L8*CcxLqGNl6^jYnmaZ+u2)6t%+2|7LqCmvxGi%c8c_l;Tlm1P0'
    'z5GNlbZFzXvGHqke{DU~)m{S17MH1wYWQgXlil=IJobI-8xp&<;67auDV8KCOb}&qrwO8CLKYHockfg@zlI>ANY5eQ`rp=ID?6?v'
    'B?bpEO6;7C`3DSU6`2hPbTQ&(l3=Y35)blcv)8Dh04c|~fuCeXy_+0`+s{!WN@zd87zt^V@NIr-AD;*5?7`{u#$L)IzsTUNszwq+'
    'kM@ZxBsC_E;So@LwSx5A4>)v09wGAL_&t<_x<lgVM7Bhb%B;-HAvuO$cMlQyio{do7>lXpzIB%@f-hl=so^5U+#qdof50?il<8v$'
    'X{xaO{A-C_;!52{E2b+*5UkMq^nRrp<R#$5qTmlN1uODDF|b%8IcOlY6OA~2BgR>mwU(o8G1Cm&8Wol+4x}|=-4XJbOMHK|s?HFw'
    '5A$&hM4X!_!1SR!;Kg1Kodk$~AaXj_Q67*_U9#Uwa#}`|uYLILyQk+O40wuvYTv+RYV@XJ#hD6B<v`(dgFxL}EOMV|j|Ll@t8DCF'
    'F^m!`!|BUP{?{hJjGBAa#9qpJd>Meo4W9)-LMw&%?uNKsB~PCsp?{3yPzjqWq28$_LckZS{PH^C9hK%0DZxoIVI^Icfk|rr7G>P='
    '$XxXAsk96s^jmUEL{1MPc{)I}n3pH%vcWtOhgJmd^T6@>(mMV<p>Z*I362NJeACZUB&LX2^}bxy<4wAklniM<9Tddvc#%Dr#sZzz'
    'snY#{>Lc>~ZdS=Rt$ODq{=}<6?pA5R9ityJNtuX}qA82IAGz|R41ob^jGr!2fUNk7Fd9RDbO()Jv(k|E#Px=q`u=4>#^V%%vKPmg'
    'BvrITDP=y|Xd$6oT4MFPY29nKH|+HdU|4t_+mU!;W@ciSK6XV-7qRG4%Uo5`nWoF`lg}z*DO29eCZ?X^9JtVJ`VXl>Uwg$ene<EJ'
    'mWwTukATfY>>qlwzQudXFoV9ty1_juGOMxmdpbqwoA)GAox2GPFvV<~ZK<i6e-LDYDka|@a_#RNBf`s7_P3*BD2P%BRzN(mhS{3f'
    'vTJc*0B|K9O*{@Clf+nzs=2pZSnl^0Zy;;e7RD}zHNW&@*y*>S6vw<8f2fmNZmD+AtOKx9c;zW+!3yi?gd?+=E%jr>3r>@zDf(9^'
    'dmCk1>%5dk'
)
_BLOWFISH_WORDS = struct.unpack("<1042I", base64.b85decode(_BLOWFISH_SCHEDULE_B85))
_BLOWFISH_P = _BLOWFISH_WORDS[:18]
_BLOWFISH_S = _BLOWFISH_WORDS[18:]


@dataclass(frozen=True, slots=True)
class SEEMode:
    index: int
    key: str
    label: str
    nx10_type: int
    columns: int
    source_lanes: tuple[int, ...]
    lightmap: bool = False


SEE_MODES = (
    SEEMode(0, "PR", "Practice", 0, 5, tuple(range(0, 5))),
    SEEMode(1, "NO", "Normal", 0, 5, tuple(range(0, 5))),
    SEEMode(2, "HD", "Hard", 0, 5, tuple(range(0, 5))),
    SEEMode(3, "NM", "Nightmare", 0, 10, tuple(range(0, 10))),
    SEEMode(4, "CR", "Crazy", 0, 5, tuple(range(0, 5))),
    SEEMode(5, "FR", "Full Double", 0, 10, tuple(range(0, 10))),
    SEEMode(6, "HF", "Half Double", 2, 6, tuple(range(2, 8))),
    SEEMode(7, "DV", "Division", 0, 5, tuple(range(0, 5))),
    SEEMode(8, "LM", "Lightmap", 10, 3, tuple(range(10, 13)), True),
)


@dataclass(frozen=True, slots=True)
class SEEChartResult:
    mode: SEEMode
    nx10_bytes: bytes
    imported: NX10ImportResult

    @property
    def document(self):
        return self.imported.document

    @property
    def report(self):
        return self.imported.report


@dataclass(frozen=True, slots=True)
class SEEImportResult:
    charts: tuple[SEEChartResult, ...]
    source_bytes: bytes
    source_name: str | None = None


@dataclass(frozen=True, slots=True)
class _SEEBlock:
    source_offset: int
    decoded: bytes


_SEE_NOTE_LOW = (
    0x00, 0xB3, 0xB2, 0xB2, 0xB2, 0xB2, 0xB2, 0x00, 0x00, 0x00,
    0xB4, 0xB6, 0xB7, 0x73, 0xC3, 0x63, 0xE3, 0x00, 0x00, 0x00,
)


def _blowfish_f(value: int) -> int:
    a = (value >> 24) & 0xFF
    b = (value >> 16) & 0xFF
    c = (value >> 8) & 0xFF
    d = value & 0xFF
    result = (_BLOWFISH_S[a] + _BLOWFISH_S[0x100 + b]) & 0xFFFFFFFF
    result ^= _BLOWFISH_S[0x200 + c]
    return (result + _BLOWFISH_S[0x300 + d]) & 0xFFFFFFFF


def _decrypt_stepedit_block(block: bytes) -> bytes:
    if len(block) != 8:
        raise ValueError("SEE Blowfish block must be exactly 8 bytes")
    left, right = struct.unpack("<II", block)
    for index in range(17, 1, -1):
        left ^= _BLOWFISH_P[index]
        right ^= _blowfish_f(left)
        left, right = right, left
    left, right = right, left
    right ^= _BLOWFISH_P[1]
    left ^= _BLOWFISH_P[0]
    return struct.pack("<II", left & 0xFFFFFFFF, right & 0xFFFFFFFF)


def _decode_compressed_block(compressed: bytes, *, source: str | None, source_offset: int) -> bytes:
    try:
        decoded = bytearray(zlib.decompress(compressed))
    except zlib.error as exc:
        raise ParseError(source_offset, "SEE zlib block", f"cannot decompress block: {exc}", source) from exc
    for position in range(0, len(decoded) - 7, 24):
        decoded[position:position + 8] = _decrypt_stepedit_block(bytes(decoded[position:position + 8]))
    return bytes(decoded)


def _read_u32(data: bytes, offset: int, label: str, source: str | None) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ParseError(max(0, offset), label, "truncated u32", source)
    return struct.unpack_from("<I", data, offset)[0]


def _validate_block(decoded: bytes, *, source: str | None, source_offset: int) -> None:
    if len(decoded) < 0x84:
        raise ParseError(source_offset, "SEE decoded block", f"decoded block is only {len(decoded)} bytes; need at least 132", source)
    bpm, beat_measure, beat_split = struct.unpack_from("<fII", decoded, 0)
    row_count = struct.unpack_from("<I", decoded, 0x80)[0]
    required = 0x84 + row_count * 13
    if required > len(decoded):
        raise ParseError(source_offset, "SEE decoded rows", f"row count {row_count} requires {required} bytes; decoded block has {len(decoded)}", source)
    if not math.isfinite(bpm) or bpm < 0.0 or bpm > 9000.0:
        raise ParseError(source_offset, "SEE decrypted BPM", f"implausible value {bpm!r}; file does not match the verified StepEdit 5.63 SEE profile", source)
    if beat_measure > 0xFF or beat_split > 0xFFFF:
        raise ParseError(source_offset, "SEE beat fields", f"implausible BeatMeasure/BeatSplit {beat_measure}/{beat_split}", source)


def _parse_sections(data: bytes, *, source: str | None) -> tuple[tuple[tuple[_SEEBlock, ...], ...] | None, ...]:
    if len(data) < SEE_HEADER_SIZE:
        raise ParseError(0, "SEE header", "file is shorter than 0x120 bytes", source)
    if data[:4] != SEE_MAGIC:
        raise ParseError(0, "SEE magic", f"expected STEE, found {data[:4]!r}", source)
    version = _read_u32(data, 4, "SEE version", source)
    if version != SEE_VERSION:
        raise ParseError(4, "SEE version", f"unsupported version {version}", source)
    offsets = struct.unpack_from("<9I", data, SEE_SECTION_TABLE_OFFSET)
    sections: list[tuple[tuple[_SEEBlock, ...], ...] | None] = []
    for mode, section_offset in zip(SEE_MODES, offsets):
        if section_offset == 0:
            sections.append(None)
            continue
        if section_offset < SEE_HEADER_SIZE or section_offset + 804 > len(data):
            raise ParseError(SEE_SECTION_TABLE_OFFSET + mode.index * 4, f"SEE {mode.label} section offset", f"offset 0x{section_offset:X} is outside the file", source)
        counts = struct.unpack_from("<200I", data, section_offset + 4)
        first_zero = next((index for index, count in enumerate(counts) if count == 0), SEE_SPLIT_SLOTS)
        if any(counts[first_zero + 1:]):
            raise ParseError(section_offset + 4 + first_zero * 4, f"SEE {mode.label} split table", "non-empty split appears after the first empty slot", source)
        position = section_offset + 804
        splits: list[tuple[_SEEBlock, ...]] = []
        for split_index, block_count in enumerate(counts[:first_zero]):
            if block_count > 1024:
                raise ParseError(section_offset + 4 + split_index * 4, f"SEE {mode.label} split {split_index} block count", f"unreasonable block count {block_count}", source)
            blocks: list[_SEEBlock] = []
            for block_index in range(block_count):
                compressed_size = _read_u32(data, position, f"SEE {mode.label} split {split_index} block {block_index} size", source)
                size_offset = position
                position += 4
                if compressed_size == 0 or compressed_size > len(data) - position:
                    raise ParseError(size_offset, f"SEE {mode.label} split {split_index} block {block_index}", f"compressed size {compressed_size} exceeds remaining file data", source)
                compressed = data[position:position + compressed_size]
                block_source_offset = position
                position += compressed_size
                decoded = _decode_compressed_block(compressed, source=source, source_offset=block_source_offset)
                _validate_block(decoded, source=source, source_offset=block_source_offset)
                blocks.append(_SEEBlock(block_source_offset, decoded))
            splits.append(tuple(blocks))
        sections.append(tuple(splits))
    return tuple(sections)


def _see_note_word(value: int) -> int:
    value &= 0xFF
    if value & 0x80:
        return 0
    if value >= 20:
        high = (value * 4 - 0x4D) & 0xFF
        return (high << 8) | 0xF1 if high < 0x54 else 0
    high = (value * 4 - 5) & 0xFF if 2 <= value <= 6 else 0
    low = _SEE_NOTE_LOW[value] if value < len(_SEE_NOTE_LOW) else 0
    return (high << 8) | low


def _block_fields(decoded: bytes):
    bpm, beat_measure, beat_split, delay = struct.unpack_from("<fIIi", decoded, 0)
    if bpm > 9000.0:
        bpm = 0.0
    scroll_raw = struct.unpack_from("<i", decoded, 0x60)[0]
    reverse = decoded[0x64] != 0
    row_count = struct.unpack_from("<I", decoded, 0x80)[0]
    speed = 1.0 if scroll_raw == 0 else scroll_raw * 0.001
    if reverse:
        speed = -speed
    row_duration = 0.0 if bpm <= 0.0 or beat_split <= 0 else 60000.0 / (bpm * beat_split)
    conditions = tuple(struct.unpack_from("<II", decoded, 0x10 + index * 8) for index in range(10))
    return bpm, beat_measure, beat_split, float(delay), speed, row_duration, row_count, conditions


def _build_nx10(mode: SEEMode, splits: tuple[tuple[_SEEBlock, ...], ...]) -> bytes:
    output = bytearray(b"NX10" + struct.pack("<III", mode.nx10_type, mode.columns, len(splits)))
    split_table = len(output)
    output += b"\x00" * (4 * len(splits))
    split_offsets: list[int] = []
    base_time = 0.0
    for split_index, blocks in enumerate(splits):
        split_offset = len(output)
        split_offsets.append(split_offset)
        output += struct.pack("<I", len(blocks))
        block_table = len(output)
        output += b"\x00" * (4 * len(blocks))
        block_offsets: list[int] = []
        first_start = first_duration = None
        for block_index, block in enumerate(blocks):
            decoded = block.decoded
            bpm, beat_measure, beat_split, delay, speed, row_duration, row_count, conditions = _block_fields(decoded)
            start_time = base_time + delay
            if block_index == 0:
                first_start = start_time
                first_duration = row_count * row_duration
            block_offset = len(output)
            block_offsets.append(block_offset)
            nx10_scroll = 0.0 if beat_split <= 0 else 1.0 / beat_split
            output += struct.pack("<fffff", start_time, bpm, nx10_scroll, delay, speed)
            division_pointer = len(output)
            output += struct.pack("<I", 0)
            output += struct.pack("<HBBI", beat_split & 0xFFFF, beat_measure & 0xFF, 0, row_count)
            if mode.lightmap:
                for row_index in range(row_count):
                    row = decoded[0x84 + row_index * 13:0x84 + (row_index + 1) * 13]
                    output += bytes(1 if row[lane] else 0 for lane in mode.source_lanes)
                    output += b"\x00"
            else:
                row_table = len(output)
                output += b"\x00" * (4 * row_count)
                if any(minimum or maximum for minimum, maximum in conditions):
                    division_offset = len(output)
                    minimums = tuple(pair[0] for pair in conditions)
                    maximums = tuple(pair[1] for pair in conditions)
                    output += struct.pack("<20I", *(minimums + maximums))
                    struct.pack_into("<I", output, division_pointer, division_offset)
                row_offsets: list[int] = []
                for row_index in range(row_count):
                    row = decoded[0x84 + row_index * 13:0x84 + (row_index + 1) * 13]
                    words = tuple(_see_note_word(value) for value in row)
                    selected = tuple(words[lane] for lane in mode.source_lanes)
                    if not any(selected):
                        row_offsets.append(0)
                        continue
                    row_offsets.append(len(output))
                    if mode.nx10_type == 2:
                        output += struct.pack("<10H", *words[:10])
                    else:
                        output += struct.pack(f"<{mode.columns}H", *selected)
                for row_index, row_offset in enumerate(row_offsets):
                    struct.pack_into("<I", output, row_table + row_index * 4, row_offset)
        for block_index, block_offset in enumerate(block_offsets):
            struct.pack_into("<I", output, block_table + block_index * 4, block_offset)
        if first_start is None:
            raise ValueError(f"SEE {mode.label} split {split_index} contains no blocks")
        base_time = first_start + (first_duration or 0.0)
    for split_index, split_offset in enumerate(split_offsets):
        struct.pack_into("<I", output, split_table + split_index * 4, split_offset)
    return bytes(output)


def import_bytes(data: bytes, *, source: str | None = None, profile: str = "nxa-native") -> SEEImportResult:
    """Decode SEE by reproducing StepEdit 5.63's native SEE -> NX10 route."""
    sections = _parse_sections(data, source=source)
    charts: list[SEEChartResult] = []
    for mode, splits in zip(SEE_MODES, sections):
        if not splits:
            continue
        nx10 = _build_nx10(mode, splits)
        output_name = f"{Path(source).stem}/{mode.key}.NX" if source else f"{mode.key}.NX"
        imported = import_nx10_bytes(nx10, source=output_name, profile=profile)
        charts.append(SEEChartResult(mode, nx10, imported))
    if not charts:
        raise ParseError(SEE_SECTION_TABLE_OFFSET, "SEE sections", "file contains no importable chart sections", source)
    return SEEImportResult(tuple(charts), data, source)


def load(path: str | Path, *, profile: str = "nxa-native") -> SEEImportResult:
    source = Path(path)
    return import_bytes(source.read_bytes(), source=str(source), profile=profile)
