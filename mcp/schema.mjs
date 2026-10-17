// A small JSON Schema checker for the subset the tool schemas use: type
// (single or a list), properties, required, items, enum, pattern, minimum and
// maximum. It exists so the contract check and the server can say "this output
// does not match what the tool promised" without a dependency in the bundle.
// Unlisted properties are allowed: a schema names what a client may rely on,
// not everything that is present.

function typeOf(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  if (Number.isInteger(value)) return 'integer';
  return typeof value;
}

const matchesType = (want, value) => {
  const got = typeOf(value);
  return got === want || (want === 'number' && got === 'integer');
};

export function validate(schema, value, path = '$') {
  const errors = [];
  if (!schema || schema === true) return errors;
  const types = schema.type === undefined ? null : [].concat(schema.type);
  if (types && !types.some((t) => matchesType(t, value))) {
    return [`${path}: expected ${types.join('|')}, got ${typeOf(value)}`];
  }
  if (schema.enum && !schema.enum.includes(value)) errors.push(`${path}: ${JSON.stringify(value)} is not one of ${schema.enum.join(', ')}`);
  if (typeof value === 'string' && schema.pattern && !new RegExp(schema.pattern).test(value)) errors.push(`${path}: does not match ${schema.pattern}`);
  if (typeof value === 'number') {
    if (schema.minimum !== undefined && value < schema.minimum) errors.push(`${path}: below ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) errors.push(`${path}: above ${schema.maximum}`);
  }
  if (Array.isArray(value) && schema.items) {
    value.forEach((item, i) => errors.push(...validate(schema.items, item, `${path}[${i}]`)));
  }
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    (schema.required || []).forEach((key) => {
      if (!(key in value)) errors.push(`${path}.${key}: missing`);
    });
    Object.entries(schema.properties || {}).forEach(([key, sub]) => {
      if (key in value) errors.push(...validate(sub, value[key], `${path}.${key}`));
    });
  }
  return errors;
}

// Short builders so a tool's schema reads like the data it describes.
export const T = {
  str: { type: 'string' },
  strNull: { type: ['string', 'null'] },
  num: { type: ['number', 'null'] },
  int: { type: ['integer', 'null'] },
  bool: { type: 'boolean' },
  any: {},
  arr: (items) => ({ type: 'array', items }),
  obj: (properties = {}, required = []) => ({ type: 'object', properties, required }),
  // A part that may be missing: null when its artifact or field was unavailable.
  maybe: (schema) => ({ ...schema, type: [].concat(schema.type || 'object', 'null') }),
};
