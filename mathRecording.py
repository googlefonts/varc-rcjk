import operator


class MathRecording:
    def __init__(self, value):
        self.value = list(value)

    def __mul__(self, scalar):
        out = []
        for v in self.value:
            if v[0] != "addPoint":
                out.append(v)
                continue
            op, (pt, segmentType, smooth, name), kwargs = v
            pt = (pt[0] * scalar, pt[1] * scalar)
            out.append((op, (pt, segmentType, smooth, name), kwargs))

        return MathRecording(out)

    def _iop(self, other, op):
        assert len(self.value) == len(other.value)
        out = []
        for v, o in zip(self.value, other.value):
            assert v[0] == o[0]
            if v[0] != "addPoint":
                out.append(v)
                continue
            op0, (pt0, segmentType0, smooth0, name0), kwargs0 = v
            op1, (pt1, segmentType1, smooth1, name1), kwargs0 = o
            assert segmentType0 == segmentType1
            # assert smooth0 == smooth1
            pt0 = (op(pt0[0], pt1[0]), op(pt0[1], pt1[1]))
            out.append((op0, (pt0, segmentType0, smooth0, name0), kwargs0))

        self.value = out
        return self

    def __isub__(self, other):
        return self._iop(other, operator.sub)

    def __iadd__(self, other):
        return self._iop(other, operator.add)
