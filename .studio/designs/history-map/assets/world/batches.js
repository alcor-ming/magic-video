// 同底图的薄纸片共用一笔提交。普通纸片的黑色接触阴影共用另一批次。
export function createCardBatches(THREE, scene) {
  const cards = [];
  const thin = [];
  const batches = new Map();
  const matrix = new THREE.Matrix4();
  const sphere = new THREE.Sphere();
  const view = new THREE.Frustum();
  const instances = (geometry, material, capacity) => {
    const mesh = new THREE.InstancedMesh(geometry, material, capacity);
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    mesh.frustumCulled = false;
    scene.add(mesh);
    return mesh;
  };
  let blobs;

  function prepare() {
    const n = cards.length;
    const geometry = new THREE.PlaneGeometry(1, 1);
    const opacity = new THREE.InstancedBufferAttribute(new Float32Array(n), 1).setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute('blobOpacity', opacity);
    const material = cards[0].blob.material.clone();
    material.opacity = 1;
    material.onBeforeCompile = shader => {
      shader.vertexShader = 'attribute float blobOpacity; varying float vBlobOpacity;\n' + shader.vertexShader.replace('#include <begin_vertex>', '#include <begin_vertex>\nvBlobOpacity = blobOpacity;');
      shader.fragmentShader = 'varying float vBlobOpacity;\n' + shader.fragmentShader.replace('#include <map_fragment>', '#include <map_fragment>\ndiffuseColor.a *= vBlobOpacity;');
    };
    blobs = { mesh: instances(geometry, material, n), opacity };
    blobs.mesh.renderOrder = 1;
    const groups = new Map();
    for (const card of thin) {
      const source = card.mesh;
      const key = [card.tex.id, source.castShadow, source.receiveShadow, card.front.roughness].join(':');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(card);
      source.visible = false;
      source.geometry.computeBoundingSphere();
    }
    for (const group of groups.values()) {
      const { mesh: source, front } = group[0];
      const material = front.clone();
      material.color.setScalar(1);
      const mesh = instances(new THREE.PlaneGeometry(1, 1), material, group.length);
      mesh.castShadow = source.castShadow;
      mesh.receiveShadow = source.receiveShadow;
      mesh.customDepthMaterial = source.customDepthMaterial;
      mesh.setColorAt(0, material.color);
      mesh.instanceColor.setUsage(THREE.DynamicDrawUsage);
      batches.set(mesh, group);
    }
  }

  function update(camera) {
    if (!cards.length) return;
    if (!blobs) prepare();
    view.setFromProjectionMatrix(matrix.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse));
    let blobCount = 0;
    for (const card of cards) {
      if (!card.root.visible) continue;
      card.root.updateMatrixWorld();
      const blob = card.blob;
      if (blob.material.opacity <= 0) continue;
      matrix.copy(blob.matrixWorld);
      if (!view.intersectsSphere(sphere.copy(blob.geometry.boundingSphere).applyMatrix4(matrix))) continue;
      blobs.mesh.setMatrixAt(blobCount, matrix);
      blobs.opacity.setX(blobCount++, blob.material.opacity);
    }
    for (const [mesh, group] of batches) {
      let count = 0;
      for (const card of group) {
        if (!card.root.visible) continue;
        const source = card.mesh;
        matrix.copy(source.matrixWorld);
        // 邻近视锥外的纸片仍可能向画面内投影。
        if (mesh.castShadow || view.intersectsSphere(sphere.copy(source.geometry.boundingSphere).applyMatrix4(matrix))) {
          matrix.multiply(card.unitToPlane);
          mesh.setMatrixAt(count, matrix);
          mesh.setColorAt(count++, card.front.color);
        }
      }
      mesh.count = count;
      mesh.visible = count > 0;
      if (count) mesh.instanceMatrix.needsUpdate = mesh.instanceColor.needsUpdate = true;
    }
    blobs.mesh.count = blobCount;
    blobs.mesh.visible = blobCount > 0;
    if (blobCount) blobs.mesh.instanceMatrix.needsUpdate = blobs.opacity.needsUpdate = true;
  }

  return {
    add(card, batchFace) {
      if (blobs) throw new Error('纸片批次须在首帧前建完');
      card.batched = true;
      card.blob.visible = false;
      card.blob.geometry.computeBoundingSphere();
      cards.push(card);
      if (batchFace) {
        card.unitToPlane = new THREE.Matrix4().makeScale(card.width, card.height, 1);
        card.unitToPlane.setPosition(0, card.height * (0.5 - card.floorV), 0);
        thin.push(card);
      }
      return card;
    },
    update,
    dispose() {
      for (const mesh of batches.keys()) mesh.dispose();
      blobs?.mesh.dispose();
    },
  };
}
